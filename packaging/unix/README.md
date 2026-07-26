# Bede install.sh (Linux and macOS installer)

Source for the Linux/macOS installer — one script covering Ubuntu, Debian,
Arch (x86_64 and arm64), and macOS (Apple Silicon and Intel). See
**[docs/UNIX_INSTALLER.md](../../docs/UNIX_INSTALLER.md)** for the design
and how it differs from the Windows side.

`install.sh.sha256` is verified against `install.sh` on every push/PR that
touches either file by `.github/workflows/verify-unix-installer-checksum.yml`
— regenerate it after any change to `install.sh`:

```bash
cd packaging/unix
sha256sum install.sh | awk '{print $1"  install.sh"}' > install.sh.sha256
```

(macOS: `shasum -a 256 install.sh | awk '{print $1"  install.sh"}' > install.sh.sha256`)
