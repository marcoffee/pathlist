# pathlist

[![test](https://github.com/marcoffee/pathlist/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/marcoffee/pathlist/actions/workflows/test.yml)
![coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)
![python](https://img.shields.io/badge/python-3.8%2B-blue)
![license](https://img.shields.io/badge/license-MIT-blue)

Edit separator-delimited path lists (`PATH`, `LD_LIBRARY_PATH`, `PKG_CONFIG_PATH`, ...): join,
exclude, deduplicate, and convert to absolute or relative paths.

A single file using only the standard library. Requires Python 3.8+.

## Install

As a superuser, copy the script to a directory on your `PATH`.

Latest release:

```sh
curl -fsSL https://github.com/marcoffee/pathlist/releases/latest/download/pathlist \
  -o /usr/local/bin/pathlist
chmod 0755 /usr/local/bin/pathlist
```

Trunk (the `main` branch, which may be ahead of the latest release):

```sh
curl -fsSL https://raw.githubusercontent.com/marcoffee/pathlist/main/pathlist \
  -o /usr/local/bin/pathlist
chmod 0755 /usr/local/bin/pathlist
```

A fixed version (recommended for scripts and images), replacing `<tag>` with a tag from the
releases page and `<sha256sum>` with the `sha256:` digest shown next to `pathlist` in that release
(without the `sha256:` prefix):

```sh
TMP_DIR="$(mktemp -d)"

curl -fsSL https://github.com/marcoffee/pathlist/releases/download/<tag>/pathlist \
  -o "${TMP_DIR}/pathlist" \
  && echo "<sha256sum> *${TMP_DIR}/pathlist" | sha256sum -c - \
  && install -m 0755 "${TMP_DIR}/pathlist" /usr/local/bin/pathlist

rm -rf "${TMP_DIR}"
```

## Usage

Each `INPUT` is a single path or a separator-joined list, and the inputs are concatenated in
order. Place the inputs first, or end the options with `--`, since `-e` and `--rel` accept values.
An input starting with `-` also needs the `--`.

#### Placing the inputs first

```sh
pathlist INPUT... [options]
```

#### Placing the inputs last

```sh
pathlist [options] -- INPUT...
```

#### Examples

```sh
# remove a directory
export LD_LIBRARY_PATH="$(pathlist "${LD_LIBRARY_PATH:-}" -e /opt/old/lib)"

# prepend, dropping duplicates (the first occurrence wins)
export PATH="$(pathlist "${HOME}/.local/bin" "${PATH}" -d)"

# append
export PKG_CONFIG_PATH="$(pathlist "${PKG_CONFIG_PATH:-}" /opt/new/lib/pkgconfig)"

# make every entry relative to /usr
pathlist /usr/lib /usr/local/lib --rel /usr
# lib:local/lib

# change the separator
pathlist "/a:/b" --output-separator ' '
# /a /b

# separate by linebreaks (bash, zsh)
pathlist "/a:/b:/c" --output-separator $'\n'
# /a
# /b
# /c

# separate by linebreaks (any shell)
pathlist "/a:/b:/c" --output-separator "
"
# /a
# /b
# /c
```

Entries are compared after normalization, so `/a/` and `/a` match for `-e` and `-d`; `--dedup-abs`
compares them by their resolved absolute path. Empty entries are dropped unless
`--no-remove-empty` is given, and output keeps each entry as written.

Run `pathlist --help` for every option.

## Tests

Run the test suite with the standard library alone:

```sh
python3 -m unittest discover -s tests
```

If you have pytest, you can run the same suite with `pytest tests`.

## License

MIT, embedded in the script header: copying the file is all it takes.
