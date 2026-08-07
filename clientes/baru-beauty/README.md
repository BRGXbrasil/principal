# Barú Beauty — BRGX

Consultoria em honorário fixo mensal. Salão na Av. Brigadeiro Faria Lima, 2128 (ao lado do Iguatemi), 7 profissionais, ~R$ 37,7 mil/mês.

## Entregáveis

| Arquivo | O que é |
|---|---|
| `relatorio-performance.html` | Relatório de Performance no template BRGX, mês de referência julho/2026 |
| `plano-acao-90-dias.html` | Plano de ação: dados, SEO local, Instagram, equipe, governança e roteiro de campo |
| `analise.py` | Extração e análise do relatório oficial do salão |
| `dados/base-tratada.csv` | Base pseudonimizada dos 3.093 lançamentos, para o acompanhamento mensal |

## Como reproduzir a análise

```bash
pip install pdfplumber
python analise.py "Relatorio_0031.pdf" --csv dados/base-tratada.csv
```

Invariantes esperados para o relatório de 07/08/2025 a 07/08/2026:
**3.093 lançamentos · R$ 377.212,85 · 720 clientes únicos · 1.999 visitas**

O relatório sai do sistema do salão em fonte 2,4pt com quatro blocos de tabela por página, e `extract_text()` puro embaralha as colunas. A extração é posicional — cada palavra é atribuída a um bloco e a uma coluna pelo `x0` — e há uma etapa de canonicalização que reconstrói os nomes corrompidos pela sobreposição dos blocos vizinhos.

## Dados pessoais

`dados/base-tratada.csv` é **pseudonimizado**: nome, telefone e CPF viram um hash estável por cliente. Todas as análises de carteira continuam possíveis (recorrência, recência, coorte, ticket) sem que o arquivo carregue dado pessoal.

A versão identificada existe só para trabalho local e **não deve ser versionada nem enviada por e-mail**:

```bash
python analise.py "Relatorio_0031.pdf" --csv /tmp/base-completa.csv --com-dados-pessoais
```

## Ressalvas registradas

- **Divergência de totais.** O cabeçalho do relatório oficial declara 3.348 itens e R$ 405.652,05; as linhas impressas somam 3.093 itens e R$ 377.212,85. Faltam 255 lançamentos na impressão — confirmar se há filtro aplicado na exportação.
- **Taxa de ocupação não calculada.** O relatório não registra duração de serviço, então o indicador saiu em branco em vez de estimado.
- **Benchmark competitivo incompleto.** Nota e volume de avaliações dos concorrentes não são obtíveis pelas buscas disponíveis; os campos marcados no plano são tarefa de coleta em campo, no Google Maps.
- **Hipótese ClassPass em aberto.** Os 410 serviços a R$ 0 podem ser reservas de plataforma lançadas sem valor. A confirmar com o extrato de repasse.
