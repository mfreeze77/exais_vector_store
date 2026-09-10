# Upstream source references

Downloaded 2026-09-10 as ordinary files from GitHub branch archives.
The folders retain upstream source layout, schemas, examples, tests, and accompanying documentation.
These copies are research material for the Kansas State Civics law-and-money backbone.

The downloaded folders stay local and are excluded from Git. This authored index
and the research write-ups are tracked; a fresh checkout does not include the
downloaded source files.

No repository revision pins or Git submodule registrations were added.
The `v1` branch of Frictionless is used because it contains the fiscal specification reviewed in this research.

| Folder | Source | Branch used | Files | Bytes |
|---|---|---|---:|---:|
| [uslm](uslm/) | [usgpo/uslm](https://github.com/usgpo/uslm) | main | 242 | 174,157,817 |
| [usaspending-api](usaspending-api/) | [fedspendingtransparency/usaspending-api](https://github.com/fedspendingtransparency/usaspending-api) | master | 1,957 | 120,372,159 |
| [openbudgets-data-model](openbudgets-data-model/) | [openbudgets/data-model](https://github.com/openbudgets/data-model) | master | 38 | 165,913 |
| [indigo](indigo/) | [laws-africa/indigo](https://github.com/laws-africa/indigo) | main | 1,498 | 39,421,164 |
| [nanopub-py](nanopub-py/) | [Nanopublication/nanopub-py](https://github.com/Nanopublication/nanopub-py) | main | 148 | 2,582,262 |
| [frictionless-datapackage-v1](frictionless-datapackage-v1/) | [frictionlessdata/datapackage](https://github.com/frictionlessdata/datapackage) | v1 | 68 | 808,364 |
| [ocds-budget-and-spend](ocds-budget-and-spend/) | [open-contracting-extensions/ocds_budget_and_spend_extension](https://github.com/open-contracting-extensions/ocds_budget_and_spend_extension) | master | 61 | 893,438 |

## Useful starting points

- [USLM identification and references](uslm/USLM-User-Guide.md); [bill-version examples](uslm/bill-version-samples-september-2024/).
- [USAspending appropriation account balances](usaspending-api/usaspending_api/accounts/models/appropriation_account_balances.py).
- [OpenBudgets components](openbudgets-data-model/components.ttl) and [code lists](openbudgets-data-model/code_lists.ttl).
- [Indigo amendment/provision models](indigo/indigo_api/models/amendments.py) and [work/commencement models](indigo/indigo_api/models/works.py).
- [Nanopublication implementation](nanopub-py/nanopub/).
- [Fiscal Data Package](frictionless-datapackage-v1/fiscal-data-package/) and [budget taxonomy](frictionless-datapackage-v1/taxonomies/fiscal/budgets.json).
- [OCDS budget/spend schema](ocds-budget-and-spend/release-schema.json).

See the [research and agreed direction](../law-and-money-backbone.md) for applicability and the existing StateCivics owners.

Archive CRC checks and extracted file sizes were verified during download. No upstream code was executed or installed.
