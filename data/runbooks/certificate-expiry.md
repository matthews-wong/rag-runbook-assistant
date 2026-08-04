# TLS Certificate Expiry

**Severity:** SEV-1
**Owner:** Platform / Networking team
**Related dashboards:** `cert-expiry-days`, `ingress-tls-errors`

## Symptoms

- Clients report `SSL certificate problem: certificate has expired` or browser
  `NET::ERR_CERT_DATE_INVALID` warnings.
- `ingress-tls-errors` spikes across all routes served by one certificate.
- Synthetic monitors fail their TLS handshake check.

## Triage

1. Confirm the expiry: `echo | openssl s_client -connect <host>:443 2>/dev/null
   | openssl x509 -noout -dates`.
2. Identify the certificate source — is it managed by cert-manager, a cloud load
   balancer, or renewed manually? Check the `cert-expiry-days` dashboard for
   which cert crossed zero.
3. If cert-manager: inspect the `Certificate` and `CertificateRequest` objects
   with `kubectl describe certificate <name> -n <ns>` for a failed renewal.

## Mitigation

- **cert-manager renewal failed:** resolve the underlying ACME challenge
  failure (usually DNS or HTTP-01 misconfiguration), then force renewal by
  deleting the `CertificateRequest` so cert-manager reissues.
- **Manual certificate:** obtain a fresh certificate from the CA and update the
  TLS secret: `kubectl create secret tls <name> --cert=... --key=... -o yaml
  --dry-run=client | kubectl apply -f -`. Reload the ingress.
- **Load-balancer-managed cert:** trigger renewal in the cloud console or via
  IaC and wait for propagation.

## Verification

- `openssl` reports a new `notAfter` date well in the future.
- `ingress-tls-errors` returns to zero and synthetic TLS checks pass.

## Prevention

- Alert at 21 days before expiry, not on the day of expiry.
- Prefer automated renewal (cert-manager / ACM) over manual certificates.

## Escalation

Expired certificates are customer-facing outages — declare SEV-1 immediately and
notify the incident commander while you renew.
