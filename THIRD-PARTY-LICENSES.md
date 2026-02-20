# Third-Party Licenses

Qubiva includes or depends on the following third-party software.

## Python Dependencies (bundled in Docker image)

| Package | License | Copyright |
|---------|---------|-----------|
| [FastAPI](https://github.com/tiangolo/fastapi) | MIT | Sebastian Ramirez |
| [Starlette](https://github.com/encode/starlette) | BSD-3-Clause | Encode |
| [Uvicorn](https://github.com/encode/uvicorn) | BSD-3-Clause | Encode |
| [Pydantic](https://github.com/pydantic/pydantic) | MIT | Pydantic Services Inc. |
| [Jinja2](https://github.com/pallets/jinja) | BSD-3-Clause | Pallets Projects |
| [Motor](https://github.com/mongodb/motor) | Apache-2.0 | MongoDB, Inc. |
| [PyMongo](https://github.com/mongodb/mongo-python-driver) | Apache-2.0 | MongoDB, Inc. |
| [asyncpg](https://github.com/MagicStack/asyncpg) | Apache-2.0 | MagicStack Inc. |
| [cryptography](https://github.com/pyca/cryptography) | Apache-2.0 OR BSD-3-Clause | The Python Cryptographic Authority |
| [defusedxml](https://github.com/tiran/defusedxml) | PSF-2.0 | Christian Heimes |
| [PyJWT](https://github.com/jpadilla/pyjwt) | MIT | Jose Padilla |
| [bcrypt](https://github.com/pyca/bcrypt) | Apache-2.0 | The Python Cryptographic Authority |
| [openai](https://github.com/openai/openai-python) | Apache-2.0 | OpenAI |
| [anthropic](https://github.com/anthropics/anthropic-sdk-python) | MIT | Anthropic |
| [kubernetes](https://github.com/kubernetes-client/python) | Apache-2.0 | The Kubernetes Authors |
| [kubernetes_asyncio](https://github.com/tomplus/kubernetes_asyncio) | Apache-2.0 | Tomasz Prus |
| [boto3](https://github.com/boto/boto3) | Apache-2.0 | Amazon Web Services |
| [azure-identity](https://github.com/Azure/azure-sdk-for-python) | MIT | Microsoft Corporation |
| [azure-mgmt-resource](https://github.com/Azure/azure-sdk-for-python) | MIT | Microsoft Corporation |
| [azure-mgmt-monitor](https://github.com/Azure/azure-sdk-for-python) | MIT | Microsoft Corporation |
| [google-auth](https://github.com/googleapis/google-auth-library-python) | Apache-2.0 | Google LLC |
| [google-cloud-monitoring](https://github.com/googleapis/google-cloud-python) | Apache-2.0 | Google LLC |
| [google-api-python-client](https://github.com/googleapis/google-api-python-client) | Apache-2.0 | Google LLC |
| [PyGithub](https://github.com/PyGithub/PyGithub) | LGPL-3.0 | PyGithub contributors |
| [GitPython](https://github.com/gitpython-developers/GitPython) | BSD-3-Clause | Sebastian Thiel, Michael Trier |
| [aiohttp](https://github.com/aio-libs/aiohttp) | Apache-2.0 | aio-libs contributors |
| [httpx](https://github.com/encode/httpx) | BSD-3-Clause | Encode |
| [requests](https://github.com/psf/requests) | Apache-2.0 | Kenneth Reitz |
| [croniter](https://github.com/kiorky/croniter) | MIT | Matsumoto Taichi |
| [Markdown](https://github.com/Python-Markdown/markdown) | BSD-3-Clause | Manfred Stienstra, Yuri Takhteyev, Waylan Limberg |
| [lxml](https://github.com/lxml/lxml) | BSD-3-Clause | lxml dev team |
| [xmlsec](https://github.com/mehcode/python-xmlsec) | MIT | Oleg Hoefling |
| [python3-saml](https://github.com/SAML-Toolkits/python3-saml) | MIT | SAML-Toolkits |

For the complete list of transitive dependencies and their licenses, see `requirements.txt`.

## Frontend Libraries (bundled in static assets)

| Library | Version | License | Copyright |
|---------|---------|---------|-----------|
| [AdminLTE](https://adminlte.io) | 3.2.0 | MIT | 2014-2022 Colorlib |
| [jQuery](https://jquery.com) | 3.6.0 | MIT | OpenJS Foundation |
| [Bootstrap](https://getbootstrap.com) | 4.6.x | MIT | Twitter, Inc. and Bootstrap Authors |
| [SweetAlert2](https://sweetalert2.github.io) | 11.4.0 | MIT | Tristan Edwards |
| [Toastr](https://github.com/CodeSeven/toastr) | 2.1.3 | MIT | John Papa, Hans Fjallemark, Tim Ferrell |
| [Font Awesome Free](https://fontawesome.com) | 5.15.4 | Font: OFL 1.1, Code: MIT, Icons: CC BY 4.0 | Fonticons, Inc. |
| [DataTables](https://datatables.net) | 1.11.4 | MIT | SpryMedia Ltd |
| [Chart.js](https://www.chartjs.org) | 2.9.4 | MIT | Chart.js Contributors |
| [Select2](https://select2.org) | 4.0.13 | MIT | Kevin Brown and contributors |
| [Moment.js](https://momentjs.com) | 2.x | MIT | Tim Wood, Iskren Chernev, Moment.js contributors |

## Runtime Dependencies (downloaded at build time, not bundled in source)

The runner Docker images download the following tools during image build.
These are separate programs executed as child processes and are **not** linked
into or distributed as part of Qubiva source code.

| Tool | License | Publisher | Notes |
|------|---------|-----------|-------|
| [Steampipe](https://steampipe.io) | AGPL-3.0 | Turbot HQ, Inc. | SQL query engine for cloud APIs. Downloaded into runner images at build time. Executed as a standalone process. |
| [Powerpipe](https://powerpipe.io) | AGPL-3.0 | Turbot HQ, Inc. | Compliance benchmark runner. Downloaded into runner images at build time. Executed as a standalone process. |
| [Steampipe Plugins](https://hub.steampipe.io) | Apache-2.0 | Turbot HQ, Inc. | Cloud provider plugins (AWS, Azure, GCP). Downloaded at runtime by Steampipe. |
| [OpenTofu](https://opentofu.org) | MPL-2.0 | The OpenTofu Authors | IaC engine (default). Downloaded into IaC runner at build time. |
| [Terraform](https://www.terraform.io) | BSL 1.1 | HashiCorp, Inc. | Alternative IaC engine (optional). Users must accept HashiCorp's license terms. |
| [Conftest](https://www.conftest.dev) | Apache-2.0 | Instrumenta | OPA policy testing tool. Downloaded into IaC runner at build time. |

### AGPL-3.0 Compliance Note

Steampipe and Powerpipe are licensed under the GNU Affero General Public
License v3.0 (AGPL-3.0). Qubiva does **not** modify these programs. They are
downloaded as pre-built binaries and executed as separate operating system
processes. Qubiva communicates with Steampipe via its PostgreSQL wire protocol
interface, not by linking to its code. The AGPL-3.0 license text is available
at https://www.gnu.org/licenses/agpl-3.0.html and is included in each
tool's binary distribution.

Qubiva itself is licensed under Apache-2.0. The use of AGPL-licensed tools
as separate processes does not change the license of Qubiva.

### Terraform BSL 1.1 Note

Terraform is licensed under the Business Source License 1.1 (BSL 1.1) by
HashiCorp, Inc. Qubiva does **not** bundle Terraform. It is an optional
alternative to the default IaC engine (OpenTofu, MPL-2.0). Users who choose
to use Terraform are responsible for complying with HashiCorp's license terms.
The BSL 1.1 license text is available at
https://github.com/hashicorp/terraform/blob/main/LICENSE .
