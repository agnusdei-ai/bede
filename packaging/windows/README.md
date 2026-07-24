# Bede Setup (Windows .msi)

Source for the Windows installer. See **[docs/WINDOWS_INSTALLER.md](../../docs/WINDOWS_INSTALLER.md)**
for the design, how to build it locally, and its current unsigned/SmartScreen caveat.

Built by `.github/workflows/build-windows-installer.yml` on `windows-latest` via:

```
dotnet build packaging/windows/BedeSetup.wixproj -c Release
```
