# DingCode releases

No certificate, password, or token belongs in this repository. CI reads them from GitHub Actions secrets at release time. If a secret is unset, that platform ships unsigned and the job still passes.

## Version

`tools/dingcode/VERSION` is the current version. The macOS bundle short version matches it. An update check runs only when `DINGCODE_UPDATE=1`. It GETs the public GitHub releases API for `DINGCODE_UPDATE_REPO` (default `hoverwr-bit/DingCode`) and prints the result. It does not send a machine id and it does not download the asset.

```
DINGCODE_UPDATE=1 python3 tools/dingcode/dingcode update
```

## Languages

`tools/dingcode/i18n/strings.json` has `zh`, `en`, and `vi`. The page and the Linux toolbar use it. Set `DINGCODE_LANG` to `zh`, `en`, or `vi`. On a page, `localStorage['dingcode-lang']` does the same. The macOS app reads the catalog from the bundle Resources, and the Windows app reads `strings.json` next to the executable.

## Tag a release

Pushing a tag `v*` runs `.github/workflows/release.yml`. It builds the three desktop packages, uploads them, and opens a GitHub Release. `workflow_dispatch` runs the same jobs without a tag.

## macOS signing and notarization

`macos/build.sh` still signs with a local **DingCode Dev** identity, then **DingAI Dev**, then **AnnoOverlay Dev**, then ad-hoc. The release job replaces that only when all of these secrets are set:

| Secret | Use |
|---|---|
| `APPLE_CERTIFICATE_P12_BASE64` | Developer ID Application certificate, base64 of the `.p12` |
| `APPLE_CERTIFICATE_PASSWORD` | Password for that `.p12` |
| `APPLE_TEAM_ID` | Team id |
| `APPLE_ID` | Apple ID for `notarytool` |
| `APPLE_APP_SPECIFIC_PASSWORD` | App-specific password for `notarytool` |

The job imports the certificate into a temporary keychain, signs `DingCode.app` with the Developer ID identity in that keychain, submits a zip to `notarytool`, and staples the ticket. The `.p12` is deleted before the job uploads the app.

## Windows signing

The release job publishes `DingCode`. It signs with `signtool` only when both secrets are set:

| Secret | Use |
|---|---|
| `WINDOWS_CERT_BASE64` | Base64 of the Authenticode `.pfx` |
| `WINDOWS_CERT_PASSWORD` | Password for that `.pfx` |

`signtool` comes from the Windows SDK already on the GitHub runner. There is no certificate file in the tree.
