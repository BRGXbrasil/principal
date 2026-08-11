#!/usr/bin/env python3
"""
Barú Beauty — extração e análise do relatório oficial de serviços.

O relatório "0031 - Serviços realizados no período" é exportado pelo sistema do
salão como um PDF de 6 páginas em fonte 2,4pt, com quatro blocos de tabela lado a
lado por página. extract_text() puro embaralha as colunas: os caracteres de blocos
vizinhos caem na mesma linha lógica e viram sopa de letras. Por isso a extração é
posicional — cada palavra é atribuída a um bloco e a uma coluna pelo x0.

Uso:
    pip install pdfplumber
    python analise.py RELATORIO.pdf [--csv dados/base-tratada.csv]

Invariantes esperados para o relatório de 07/08/2025 a 07/08/2026:
    3.093 lançamentos | R$ 377.212,85 | 720 clientes únicos | 1.999 visitas
"""

import argparse
import collections
import csv
import datetime
import hashlib
import re
import sys

import pdfplumber

# Os quatro blocos de tabela por página, em deslocamento no eixo x.
BLOCK_OFFSETS = [0.0, 139.8, 279.6, 419.4]
BLOCK_WIDTH = 155.0

# x0 de cada coluna, em coordenadas do primeiro bloco.
COLUMNS = [
    ("profissional", 24.0),
    ("data", 40.0),
    ("dia_semana", 50.6),
    ("comanda", 60.2),
    ("servico", 70.9),
    ("categoria", 84.9),
    ("cliente", 95.7),
    ("cpf", 114.0),
    ("telefone", 129.0),
    ("quantidade", 140.0),
    ("valor", 146.0),
]

# Campos que podem ocupar mais de uma linha e precisam ser concatenados.
WRAPPING_FIELDS = ("profissional", "servico", "categoria", "cliente")

DATE_RE = re.compile(r"\d{2}/\d{2}/\d{4}")

# Rótulos que nunca são impressos numa linha limpa — em toda ocorrência as letras
# vêm intercaladas com as do bloco vizinho, então não há forma correta para o
# vocabulário aprender. Reescritos à mão a partir da leitura do PDF.
ALIASES = {
    "manicureepedicure": "Manicure e Pedicure",
    "tinturacomoprodutodosalão": "Tintura com o produto do Salão",
    "tinturacomoprodutodocliente": "Tintura com o produto do cliente",
    "progressivarichee": "Progressiva Richee",
    "hidrataçãoprofundasebastian": "Hidratação Profunda Sebastian",
    "hidrataçãoporfundakerastase": "Hidratação Profunda Kerastase",
    "retirarunhadefibra": "Retirar Unha de Fibra",
    "blindagemdeunha": "Blindagem de Unha",
    "carlosalexandrehenter": "Carlos Alexandre Henter",
    "nayaneoliveira": "Nayane Oliveira",
    "gabrielamariadossantos": "Gabriela Maria dos Santos",
    "bioestimuladordecolágeno": "Bioestimulador de colágeno",
    "massagemrelaxante": "Massagem Relaxante",
    "massagemmodeladora": "Massagem Modeladora",
    "massagemlinfaticaedrenagem": "Massagem Linfática e Drenagem",
    "reconstruçãoitalian": "Reconstrução Italian",
    "lavagemespecialcomsecagem": "Lavagem Especial com secagem",
    "remoçãodecílios": "Remoção de Cílios",
    "lavieenfullfacerostotodoavulso": "Lavieen - Full Face - Rosto Todo - Avulso",
}


def column_for(x):
    """Nome da coluna cujo x0 é o maior que ainda cabe antes de x."""
    found = None
    for name, anchor in COLUMNS:
        if x >= anchor - 1.2:
            found = name
        else:
            break
    return found


def extract(pdf_path):
    """Devolve os lançamentos do PDF como lista de dicts, na ordem de impressão."""
    records = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(x_tolerance=0.8, y_tolerance=0.8)
            for offset in BLOCK_OFFSETS:
                block = [w for w in words if offset + 23.0 <= w["x0"] < offset + BLOCK_WIDTH]
                lines = collections.defaultdict(list)
                for word in block:
                    lines[round(word["top"], 1)].append(word)

                current = None
                for top in sorted(lines):
                    cells = collections.defaultdict(list)
                    for word in sorted(lines[top], key=lambda w: w["x0"]):
                        column = column_for(word["x0"] - offset)
                        if column:
                            cells[column].append(word["text"])
                    cells = {k: " ".join(v) for k, v in cells.items()}

                    # Uma data na coluna "data" abre um lançamento novo; qualquer
                    # outra linha é continuação de célula quebrada do anterior.
                    if DATE_RE.fullmatch(cells.get("data", "")):
                        current = {name: cells.get(name, "") for name, _ in COLUMNS}
                        current["pagina"] = page_number
                        records.append(current)
                    elif current is not None:
                        for field in WRAPPING_FIELDS:
                            if cells.get(field):
                                current[field] = (current[field] + " " + cells[field]).strip()
    return records


def squash(text):
    """Chave de comparação sem espaços — 'A l i n e' e 'Aline' colidem de propósito."""
    return re.sub(r"[^0-9a-zA-Zçãáéíóúâêôõà]", "", text).lower()


def canonicalize(records, field):
    """
    Corrige nomes corrompidos pela sobreposição de blocos.

    Quando duas linhas de blocos vizinhos caem no mesmo `top`, as palavras se
    intercalam e "Aline" vira "A l i n e", às vezes com lixo colado no fim
    ("Aline A l i n e A l i n e"). A correção monta um vocabulário com as
    ocorrências limpas do campo — as que não têm tokens de uma letra só — e casa
    cada valor sujo pelo prefixo da forma sem espaços, preferindo o vocábulo mais
    longo para não truncar "Aline Bispo Pereira" em "Aline".
    """
    # "e", "o" e "a" são palavras legítimas em português ("Lavagem e Secagem",
    # "Tintura com o produto"); qualquer outra letra solta é resíduo da
    # intercalação de blocos.
    particles = {"e", "o", "a"}

    def is_clean(value):
        # A comparação é sensível a caixa de propósito: "e" é conjunção, "E" solto
        # é letra vazada de "Escova".
        return not any(len(t) == 1 and t.isalpha() and t not in particles for t in value.split())

    clean = collections.Counter()
    for record in records:
        value = re.sub(r"\s+", " ", record[field]).strip()
        if value and is_clean(value):
            clean[value] += 1
    # Os aliases entram no vocabulário para cobrir os rótulos sem forma limpa.
    vocabulary = sorted(set(clean) | set(ALIASES.values()), key=lambda v: -len(squash(v)))

    cache = {}
    for record in records:
        key = squash(record[field])
        if key not in cache:
            fallback = re.sub(r"\s+", " ", record[field]).strip()
            cache[key] = next((v for v in vocabulary if key.startswith(squash(v))), fallback)
        record[field] = cache[key]


def to_float(value):
    try:
        return float(value.replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def enrich(records):
    """Normaliza tipos e deriva a identidade da cliente e a chave de visita."""
    for record in records:
        record["valor_num"] = to_float(record["valor"])
        day, month, year = record["data"].split("/")
        record["data_iso"] = f"{year}-{month}-{day}"
        record["mes"] = f"{year}-{month}"
        record["dt"] = datetime.date(int(year), int(month), int(day))

        # O telefone é o identificador mais estável: o mesmo nome aparece grafado
        # de várias formas ("Luciana" vs "Luciana Marcelino de Carvalho").
        phone = re.sub(r"\D", "", record["telefone"])
        record["cliente_id"] = phone if len(phone) >= 10 else "nome:" + squash(record["cliente"])
    return records


def load(pdf_path):
    records = extract(pdf_path)
    for field in WRAPPING_FIELDS:
        canonicalize(records, field)
    records = enrich(records)
    # O relatório às vezes traz lançamentos anteriores à data de início do filtro.
    return [r for r in records if r["dt"] >= datetime.date(2025, 8, 1)]


# ---------------------------------------------------------------- análises


def by_month(records):
    """Receita, visitas, ticket e composição novas/recorrentes por mês."""
    visits = group_visits(records)
    first_visit = {}
    for visit in sorted(visits.values(), key=lambda v: v["dt"]):
        first_visit.setdefault(visit["cliente_id"], visit["dt"])

    rows = collections.defaultdict(
        lambda: {"receita": 0.0, "visitas": 0, "servicos": 0, "novas": 0, "recorrentes": 0}
    )
    for visit in visits.values():
        row = rows[visit["dt"].strftime("%Y-%m")]
        row["receita"] += visit["valor"]
        row["visitas"] += 1
        row["servicos"] += visit["n_servicos"]
        if first_visit[visit["cliente_id"]].strftime("%Y-%m") == visit["dt"].strftime("%Y-%m"):
            row["novas"] += 1
        else:
            row["recorrentes"] += 1
    return dict(sorted(rows.items()))


def group_visits(records):
    """Uma visita = uma cliente num dia. É a unidade real de ticket médio."""
    visits = collections.defaultdict(
        lambda: {"valor": 0.0, "n_servicos": 0, "servicos": [], "cliente_id": "", "dt": None}
    )
    for record in records:
        visit = visits[(record["cliente_id"], record["dt"])]
        visit["valor"] += record["valor_num"]
        visit["n_servicos"] += 1
        visit["servicos"].append(record["servico"])
        visit["cliente_id"] = record["cliente_id"]
        visit["dt"] = record["dt"]
    return visits


def by_dimension(records, field):
    """Receita, volume e alcance de clientes por categoria, serviço ou profissional."""
    rows = collections.defaultdict(lambda: {"receita": 0.0, "servicos": 0, "clientes": set()})
    for record in records:
        row = rows[record[field]]
        row["receita"] += record["valor_num"]
        row["servicos"] += 1
        row["clientes"].add(record["cliente_id"])
    return dict(sorted(rows.items(), key=lambda kv: -kv[1]["receita"]))


def wallet(records):
    """Segmenta a carteira por recência a partir da última data do relatório."""
    end = max(r["dt"] for r in records)
    clients = collections.defaultdict(
        lambda: {"valor": 0.0, "dias": set(), "categorias": set(), "nome": ""}
    )
    for record in records:
        client = clients[record["cliente_id"]]
        client["valor"] += record["valor_num"]
        client["dias"].add(record["dt"])
        client["categorias"].add(record["categoria"])
        client["nome"] = record["cliente"]

    buckets = {"ativas": [], "em_risco": [], "perdidas": []}
    for client in clients.values():
        idle = (end - max(client["dias"])).days
        bucket = "ativas" if idle <= 60 else "em_risco" if idle <= 180 else "perdidas"
        buckets[bucket].append(client)
    return clients, buckets


def retention(records):
    """Recompra da iluminação capilar e attach rate de tratamento sobre química."""
    lighting_terms = ("reflexo", "luzes", "mechas", "balayage", "iluminação", "morena iluminada")
    lighting = [r for r in records if any(t in r["servico"].lower() for t in lighting_terms)]
    lighting_clients = collections.defaultdict(set)
    for record in lighting:
        lighting_clients[record["cliente_id"]].add(record["dt"])

    chemical_terms = ("Reflexo", "Luzes", "Tintura", "Retoque", "Tonalização", "Progressiva", "Botox")
    care_terms = ("Tratamento", "Hidrat", "Reconstru", "Cronograma")
    visits = group_visits(records).values()
    chemical = [v for v in visits if any(t in " ".join(v["servicos"]) for t in chemical_terms)]
    with_care = [v for v in chemical if any(t in " ".join(v["servicos"]) for t in care_terms)]

    return {
        "iluminacao_servicos": len(lighting),
        "iluminacao_receita": sum(r["valor_num"] for r in lighting),
        "iluminacao_clientes": len(lighting_clients),
        "iluminacao_repetiram": sum(1 for d in lighting_clients.values() if len(d) > 1),
        "quimica_visitas": len(chemical),
        "quimica_com_tratamento": len(with_care),
    }


def turnover(records, janela_ativo_dias=45):
    """
    Rotatividade de equipe: quem ainda está x quem já saiu, e quanto cada um levou.

    "Ativo" = teve ao menos um lançamento nos últimos `janela_ativo_dias` a partir
    da última data do relatório. É uma aproximação por ausência de cadastro de
    desligamento — funciona bem quando a saída é abrupta, como neste caso.
    """
    end = max(r["dt"] for r in records)
    first = {}
    last = {}
    receita = collections.defaultdict(float)
    for r in records:
        prof = r["profissional"]
        if not prof or len(prof) < 4:
            continue
        first[prof] = min(first.get(prof, r["dt"]), r["dt"])
        last[prof] = max(last.get(prof, r["dt"]), r["dt"])
        receita[prof] += r["valor_num"]

    ativos = [p for p in last if (end - last[p]).days <= janela_ativo_dias]
    sairam = [p for p in last if (end - last[p]).days > janela_ativo_dias]
    sairam.sort(key=lambda p: -receita[p])

    return {
        "total_profissionais": len(first),
        "ativos": ativos,
        "sairam": sairam,
        "receita_sairam": sum(receita[p] for p in sairam),
        "receita_total": sum(receita.values()),
        "ultima_data": {p: last[p] for p in last},
        "receita_por_profissional": dict(receita),
    }


def export_csv(records, path, anonimo=True):
    """
    Exporta a base tratada.

    Por padrão sai pseudonimizada: nome, telefone e CPF viram um hash estável por
    cliente. Todas as análises de carteira (recorrência, recência, coorte) seguem
    possíveis, mas o arquivo deixa de conter dado pessoal e pode ser versionado.
    Use anonimo=False só para trabalho local — o resultado não deve ir para o
    repositório nem ser enviado por e-mail.
    """
    if anonimo:
        fields = [
            "data_iso", "dia_semana", "profissional", "servico",
            "categoria", "cliente_hash", "quantidade", "valor_num",
        ]
        for record in records:
            digest = hashlib.sha256(("baru:" + record["cliente_id"]).encode())
            record["cliente_hash"] = digest.hexdigest()[:12]
    else:
        fields = [
            "data_iso", "dia_semana", "comanda", "profissional", "servico",
            "categoria", "cliente", "cliente_id", "telefone", "quantidade", "valor_num",
        ]

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(records, key=lambda r: r["data_iso"]))


def brl(value):
    return f"R$ {value:,.0f}".replace(",", ".")


def report(records):
    total = sum(r["valor_num"] for r in records)
    visits = group_visits(records)
    clients, buckets = wallet(records)

    print(f"Lançamentos: {len(records)}  Receita: {brl(total)}")
    print(f"Clientes únicos: {len(clients)}  Visitas: {len(visits)}")
    print(f"Ticket por visita: {brl(total / len(visits))}")
    print(f"Serviços por visita: {len(records) / len(visits):.2f}")

    zeroed = [r for r in records if r["valor_num"] == 0]
    print(f"Serviços a R$ 0: {len(zeroed)} ({len(zeroed) / len(records) * 100:.1f}%)")

    once = [c for c in clients.values() if len(c["dias"]) == 1]
    print(f"Clientes de visita única: {len(once)} ({len(once) / len(clients) * 100:.1f}%)")
    for name, group in buckets.items():
        print(f"  {name}: {len(group)} clientes | histórico {brl(sum(c['valor'] for c in group))}")

    print("\nMês        Receita   Visitas  Ticket  Serv/vis  Novas  Recorr")
    for month, row in by_month(records).items():
        print(
            f"{month}  {row['receita']:>10,.0f}  {row['visitas']:>7}  "
            f"{row['receita'] / row['visitas']:>6.0f}  {row['servicos'] / row['visitas']:>8.2f}  "
            f"{row['novas']:>5}  {row['recorrentes']:>6}"
        )

    print("\nCategorias:")
    for name, row in list(by_dimension(records, "categoria").items())[:8]:
        print(
            f"  {name[:32]:34s} {brl(row['receita']):>12}  {row['receita'] / total * 100:>5.1f}%  "
            f"{row['servicos']:>5} serv  {len(row['clientes']):>4} cli"
        )

    print("\nTop serviços por receita:")
    for name, row in list(by_dimension(records, "servico").items())[:12]:
        print(
            f"  {name[:36]:38s} {brl(row['receita']):>11}  {row['servicos']:>5}x  "
            f"médio {brl(row['receita'] / row['servicos'])}"
        )

    print("\nProfissionais:")
    for name, row in list(by_dimension(records, "profissional").items())[:12]:
        print(
            f"  {name[:34]:36s} {brl(row['receita']):>11}  {row['receita'] / total * 100:>5.1f}%  "
            f"{row['servicos']:>5} serv  médio {brl(row['receita'] / row['servicos'])}"
        )

    turn = turnover(records)
    print("\nRotatividade de equipe:")
    print(
        f"  {turn['total_profissionais']} profissionais no período | "
        f"{len(turn['ativos'])} ativos | {len(turn['sairam'])} saíram "
        f"({len(turn['sairam']) / turn['total_profissionais'] * 100:.0f}%)"
    )
    print(
        f"  Receita que saiu com quem foi embora: {brl(turn['receita_sairam'])} "
        f"({turn['receita_sairam'] / turn['receita_total'] * 100:.0f}% do total)"
    )

    stats = retention(records)
    print("\nIluminação capilar (o carro-chefe declarado):")
    print(
        f"  {stats['iluminacao_servicos']} serviços | {brl(stats['iluminacao_receita'])} "
        f"({stats['iluminacao_receita'] / total * 100:.1f}% da receita)"
    )
    print(
        f"  {stats['iluminacao_clientes']} clientes, "
        f"{stats['iluminacao_repetiram']} repetiram "
        f"({stats['iluminacao_repetiram'] / stats['iluminacao_clientes'] * 100:.0f}%)"
    )
    print(
        f"  Attach de tratamento sobre química: {stats['quimica_com_tratamento']}/"
        f"{stats['quimica_visitas']} "
        f"({stats['quimica_com_tratamento'] / stats['quimica_visitas'] * 100:.1f}%)"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="Relatório 0031 exportado do sistema do salão")
    parser.add_argument("--csv", help="Caminho para exportar a base tratada (pseudonimizada)")
    parser.add_argument(
        "--com-dados-pessoais",
        action="store_true",
        help="Inclui nome, telefone e CPF no CSV. Uso local apenas — não versionar.",
    )
    args = parser.parse_args()

    records = load(args.pdf)
    if not records:
        sys.exit("Nenhum lançamento extraído — confira se o PDF é o relatório 0031.")

    report(records)
    if args.csv:
        export_csv(records, args.csv, anonimo=not args.com_dados_pessoais)
        aviso = " COM DADOS PESSOAIS — não versionar" if args.com_dados_pessoais else " (pseudonimizada)"
        print(f"\nBase exportada em {args.csv}{aviso}")


if __name__ == "__main__":
    main()
