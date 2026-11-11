# Publisher signing

No usable code-signing certificate or SignTool was found in this workspace.
No signature has been created. Do not publish a self-signed certificate as if
it establishes a trusted publisher.

Obtain access to a publicly trusted Authenticode certificate/signing service
for Alpha Makuza and install the Windows SDK SignTool. Certificate enrollment
and private-key access are publisher actions; keep private keys/passwords out
of this repository and chat. Provider purchases need the publisher's choice.

For a certificate exposed in the current user's Windows certificate store:

```powershell
.\scripts\sign_release.ps1 -CertificateThumbprint YOUR_CERT_THUMBPRINT -TimestampUrl YOUR_PROVIDER_RFC3161_URL
```

The helper signs only the application's EXE, uses SHA-256 plus an RFC 3161
timestamp, then verifies with Authenticode policy. Existing third-party library
signatures remain untouched. A cloud/HSM provider may require its own signing
client or SignTool configuration instead.

Sign the final executable before ZIP creation. Then run
`python -m scripts.package_release` to refresh signature metadata and recreate
the ZIP/checksum, and repeat package validation. Rebuilding afterward
replaces the signed executable. A valid signature identifies the publisher;
it does not guarantee Windows SmartScreen will show no warning.

Microsoft references:

- https://learn.microsoft.com/windows/win32/seccrypto/signtool
- https://learn.microsoft.com/windows/win32/seccrypto/time-stamping-authenticode-signatures
