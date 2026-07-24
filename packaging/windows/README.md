# Bede Setup (Windows installer)

Source for the Windows installer, built with [Inno Setup](https://jrsoftware.org/isinfo.php).
See **[docs/WINDOWS_INSTALLER.md](../../docs/WINDOWS_INSTALLER.md)**
for the design, how to build it locally, and its code-signing setup.

Built by `.github/workflows/build-windows-installer.yml` on `windows-latest` via:

```
ISCC.exe packaging/windows/BedeSetup.iss
```
