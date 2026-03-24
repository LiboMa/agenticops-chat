# Cloud Provider Status Pages & Public APIs

## Cloud Status Pages

| Provider | Status Page URL | Format |
|----------|----------------|--------|
| **AWS** | `https://health.aws.amazon.com/health/status` | HTML |
| **AWS (JSON)** | `https://health.aws.amazon.com/health/status.json` | JSON |
| **Azure** | `https://status.azure.com/en-us/status` | HTML |
| **GCP** | `https://status.cloud.google.com/` | HTML |
| **GCP (JSON)** | `https://status.cloud.google.com/incidents.json` | JSON |
| **Alibaba Cloud** | `https://status.alibabacloud.com/` | HTML |
| **GitHub** | `https://www.githubstatus.com/` | HTML |
| **GitHub (API)** | `https://www.githubstatus.com/api/v2/status.json` | JSON |
| **Datadog** | `https://status.datadoghq.com/` | HTML |
| **PagerDuty** | `https://status.pagerduty.com/` | HTML |
| **Cloudflare** | `https://www.cloudflarestatus.com/` | HTML |

## CVE / Vulnerability Databases

| Source | URL Pattern | Notes |
|--------|-------------|-------|
| **NVD (NIST)** | `https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-YYYY-NNNNN` | JSON, free, rate-limited |
| **NVD keyword** | `https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=KEYWORD` | Search by keyword |
| **CISA KEV** | `https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json` | Known Exploited Vulns |

## Package Registries

| Registry | URL Pattern | Notes |
|----------|-------------|-------|
| **PyPI** | `https://pypi.org/pypi/PACKAGE/json` | Python package info |
| **npm** | `https://registry.npmjs.org/PACKAGE` | Node.js package info |
| **Docker Hub** | `https://hub.docker.com/v2/repositories/NAMESPACE/IMAGE/tags` | Container tags |

## Usage Tips

1. **Prefer JSON endpoints** — easier to parse, no HTML stripping needed
2. **Check status pages first** when multiple resources show the same symptoms
3. **Use HEAD method** to quickly check if a URL is reachable without downloading content
4. **NVD rate limit**: ~5 requests per 30 seconds without API key
5. **HTML pages**: web_fetch auto-strips tags; for complex pages, content may be incomplete
