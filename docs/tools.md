# Tools and workflow

## Requirements

| Tool | Version tested | Used for |
|---|---|---|
| Python | 3.11 | All scripts (needs `tomllib`) |
| Ghidra | 11.3.1 | Analysis. PyGhidra ships with it |
| Java (JDK) | 17 | Ghidra |
| 7-Zip (`7z`) | any | Extracting the firmware from the updater |
| `curl`, `sha256sum`, `make` | any | Downloading and checking the SVD |
| `arm-none-eabi-binutils` | any | Quick disassembly (optional) |
| OpenOCD | any | SWD access (M4, optional for now) |

If Ghidra is not in `/opt/ghidra_11.3.1_PUBLIC`, pass its location:
`make ghidra GHIDRA_INSTALL_DIR=/path/to/ghidra`.

## First time

```bash
make setup                                              # .venv with PyGhidra
make baserom SRC=~/Downloads/MPK_mini_Plus_Updater_v1.13.exe
make ghidra                                             # ~20 s
```

Then open `build/ghidra/hackai-mpk.gpr` in Ghidra.

## Daily loop

1. Work in Ghidra: rename functions and labels, add plate comments.
2. Save, close the project and run `make export`. Your names go to
   `config/symbols.csv`.
3. Review with `git diff config/symbols.csv` and commit.

`make report` writes analysis reports to `build/reports/` (not in git):

- `peripherals.md`: for each peripheral, the functions that use it and which
  registers they read or write.
- `peripherals.csv`: for each function, the peripherals it uses directly and
  through the functions it calls.

When `config/` changes (yours or someone else's), run `make rebuild`. It
exports first, so nothing is lost, and then builds the project from scratch.

## What `make ghidra` does

`tools/ghidra/build_project.py` creates the program without Ghidra's
importer, so every step comes from `config/`:

1. One memory block per segment of `config/segments.toml`, plus RAM.
   Only executable segments are disassembled.
2. The AT32F415 SVD (downloaded once from a pinned commit and checked by
   SHA-256): one volatile block per peripheral, a register structure applied at
   its base address, and a label.
3. Both vector tables: each handler becomes a function named after its
   exception or SVD interrupt (`USART1_IRQHandler`, with the suffix `_BL` in
   the bootloader).
4. The names and notes of `config/symbols.csv`.
5. Auto-analysis, after which the names of step 4 are applied again.

## `config/symbols.csv`

| Column | Meaning |
|---|---|
| `address` | Absolute address, `0x0800ABCD` |
| `kind` | `func` or `label` |
| `name` | A valid C identifier, unique. Bootloader symbols end in `_BL` |
| `type` | C type or signature (used from M1 `types.h` on) |
| `status` | See below |
| `notes` | Short free text, shown as a plate comment in Ghidra |

Status values, from least to most understood:

| Status | Meaning |
|---|---|
| `named` | Has a meaningful name, maybe a guess (`_POSSIBLE` suffix) |
| `typed` | Signature and types are right |
| `understood` | Behaviour documented in `docs/` |
| `reimplemented` | Has a C reimplementation that passes the equivalence tests |

Rows are never deleted by `make export`. To remove a name, delete its row by
hand (or use `export_symbols.py --prune`).
