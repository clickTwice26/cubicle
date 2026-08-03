# Problem statement and requirements

**Localoy, engineering brief, issued to prospective suppliers**

| | |
| --- | --- |
| From | Engineering, Localoy (`localoy.app`) |
| Issued | 20 July 2026 |
| Response due | 5 August 2026 |

The requirements in sections 6 and 7 are numbered and are to be read literally.
If one of them is unreasonable, we expect to be told during evaluation rather
than during delivery.

---

## 1. Context

Localoy operates `localoy.app`, which is built as microservices, each owning its
own database and deployed independently. Whatever the service, anything reaching
production follows the same path: code review, the full automated test suite, a
staging soak, and a scheduled release window. That process is not under review.

Our infrastructure is self-hosted and will remain so.

---

## 2. Problem statement

Small server-side additions carry the same delivery cost as substantial ones,
because our architecture offers only two routes to production.

The first route is to add the functionality to an existing service, where it
inherits that service's release process and database despite having no
functional relationship to its purpose. A form that persists five fields follows
the same path to production as a change to checkout.

The second route is to create a service for it, which incurs the full cost of a
service in our estate: a repository, a pipeline, a database, monitoring and an
assigned out-of-hours owner. That cost is appropriate for a business capability
and disproportionate for a feedback form.

The consequence is not delayed delivery but non-delivery. The following requests
illustrate the pattern.

| Request | Outcome |
| --- | --- |
| An NPS survey to follow a completed booking | The request was raised on 11 February and estimated at half a day. It has been scheduled three times and has not been delivered. |
| A feedback widget for three marketing pages | Marketing implemented it on an external form product. The responses are now held in a third-party account that nobody administers. |
| A partner callback for a pilot integration | It reached production in nine days for fewer than 100 lines of code, and the partner raised the delay with us. |
| A tool to correct mis-tagged listings | The tool was never built, and the records are corrected by hand approximately once a week. |
| Waiting-list capture for a beta feature | It was delivered, but it consumed a release slot and deferred the associated feature by one cycle. |

Four further requests of this type are queued, and on past evidence most of them
will not be prioritised.

We have considered an expedited release path for low-risk changes and rejected
it, because such a path still places the code inside a production service and
its database. Separation from the production estate is a primary objective of
this engagement.

### 2.1 A second requirement: functions our own services can call

Separately from the endpoints described above, we need somewhere to put small
units of work that several services need and none of them owns. Two current
examples are compressing an image before it is uploaded to our object storage,
and extracting the dominant colours from an image once it is stored.

At present each service either implements this itself or takes a shared library,
and neither is satisfactory. Separate implementations diverge over time. A shared
library means that changing the compression settings obliges every consuming
service to take the new version and pass through the full release process, which
returns us to the problem described above.

We therefore require these functions to be callable over HTTP by our production
services. We recognise that this places the platform closer to a production path
than the endpoints in the table above, and we accept that. The design must allow
a calling service to degrade rather than fail when the platform is unavailable,
and the requirements in section 6 and section 7 reflect this.

---

## 3. Options assessed

| Option | Assessment |
| --- | --- |
| A managed functions provider | It introduces a supplier, an invoice and consumption-based spend that we cannot forecast, and it would hold customer feedback outside our control. |
| A hosted survey product | It addresses surveys only, and several of the requests above are not surveys. The second row of that table shows where this leads over time. |
| A dedicated service per use case | This is our standard pattern and it is correct where a business capability justifies it. Here the service would cost more than the functionality it contains. |
| An existing self-hosted platform | The mature options assume a dedicated platform operator, and our infrastructure team is fully committed. |

We are therefore seeking a purpose-built solution that is delivered to us and
operated by us.

---

## 4. Constraints

The following are not negotiable, and a proposal that fails any of them cannot
be accepted.

| | |
| --- | --- |
| **C1** | It must not be part of, connected to, or deployed alongside any production service, and it must not become an additional service in our estate. |
| **C2** | It must run on hardware we own, and we must retain administrative access to it. |
| **C3** | It must introduce no recurring payment to any third party, whether a subscription, consumption billing or seat licensing. |
| **C4** | No customer data may leave our infrastructure, and no component may report telemetry externally. |
| **C5** | We must hold the source outright, with the right to use and modify it independently of the supplier. |
| **C6** | It must be operable by our existing team, without additional headcount or a new specialism. |

---

## 5. Resources available

| | |
| --- | --- |
| Hardware | We can provide one dedicated virtual server with 4 cores, 8 GB of memory and 30 GB of storage, routable on our network. This is what we can release for the platform, and we would rather hear that it is insufficient than discover it in month six. A second machine of the same specification can follow if capacity requires it. |
| Expected load | We expect 15 to 40 functions, idle for most of the day. The highest-volume endpoint will be an NPS survey receiving approximately 2,000 submissions over 48 hours. Headroom is required for 50 requests per second, and the data is small and text-based. |
| Users | Product engineers from several service teams will use it, not infrastructure staff alone. |
| Access | We will provide a subdomain of `localoy.app` with DNS under our control. |
| Personnel | We can allocate an infrastructure engineer for half a day per week, which is our limit, and a named contact who signs off at each stage. |

---

## 6. Functional requirements

**M** must be met for the work to be accepted. **S** is expected, and we are to
be consulted before it is descoped. **N** will not delay delivery.

### Installation

| | | |
| --- | --- | --- |
| **F1** | The platform must install in a single step, generate its own internal credentials, and be safe to re-run without affecting deployed functions. | M |
| **F2** | It must serve HTTPS on a subdomain we control, and renew its certificates automatically. | M |
| **F3** | It must require no external account or registration at any point. | M |

### Creating an endpoint

| | | |
| --- | --- | --- |
| **F4** | An engineer must be able to author, deploy and test a function through a browser with nothing installed locally, and this must be available to product engineers as well as to infrastructure staff. | M |
| **F5** | Functions must be organised into named groups, so that the work of different teams is kept separate. | M |
| **F6** | A deployment must produce a working HTTPS endpoint that we can use in a page or give to a partner. | M |
| **F7** | A function must be able to declare third-party dependencies, which the platform then installs. | M |
| **F8** | Each deployment must create a new version, and the previous version must continue to serve until the new one is ready, with no interval of failed requests. | M |
| **F9** | Deployment of a small function must complete within two minutes. | M |
| **F10** | A function should be revertible to a previous version without being rebuilt. | S |
| **F11** | The same operations should be available from a command line. | S |

### Serving traffic

| | | |
| --- | --- | --- |
| **F12** | Endpoints must require a credential by default, and an individual endpoint must be able to be made public so that it accepts anonymous submissions. | M |
| **F13** | The platform must handle concurrent requests to one function, and an idle function must consume no resources. | M |
| **F14** | It must be possible to limit the resources that a single function may consume. | M |
| **F15** | A function should be able to reserve capacity, so that a customer-facing form incurs no start-up delay after a period of inactivity. | S |
| **F16** | The platform may support scheduled execution in addition to HTTP invocation. | N |

### Data and configuration

| | | |
| --- | --- | --- |
| **F17** | Persistent storage must be provisioned on request and connected to functions by the platform, without users handling credentials. | M |
| **F18** | Short-lived storage should be available for caching and rate limiting. | S |
| **F19** | Configuration must be held centrally, a change must take effect without redeployment, and values marked secret must be encrypted and not displayed after entry. | M |
| **F20** | An administrator should be able to read, correct and export stored records, including through ad-hoc queries. | S |

### Operation and monitoring

| | | |
| --- | --- | --- |
| **F21** | Every invocation must be recorded, request volume and error rate must be reported, and 30 days of history must be retained. | M |
| **F22** | A function's output and errors must be available in real time while it runs. | M |
| **F23** | The platform must show its own status and its remaining capacity. | M |
| **F24** | Metrics should be exposed in a form that our existing monitoring can collect. | S |
| **F25** | The platform may raise an alert when a function's error rate increases. | N |
| **F26** | Resource usage may be attributed to the group responsible for it. | N |

### Access control

| | | |
| --- | --- | --- |
| **F27** | The platform must support multiple accounts with distinct roles, assignable per environment, so that permission to view logs is separable from permission to deploy. | M |
| **F28** | It must support at least two environments on one instance, production and staging, each invisible to the other. | M |
| **F29** | Access must be withdrawable in a single action that also terminates any active session. | M |
| **F30** | It may be extended onto a second server without being rebuilt. | N |

### Documentation

| | | |
| --- | --- | --- |
| **F31** | Documentation must be provided within the product, covering installation, authoring, configuration, data and routine operations, and it must correspond to the version in use. | M |

### Functions called by our own services

These requirements support section 2.1.

| | | |
| --- | --- | --- |
| **F32** | Our production services must be able to invoke a function over HTTP using a credential issued to the calling service, and each such credential must be revocable independently of the others. | M |
| **F33** | A function must accept and return binary payloads, including images of at least 10 MB. | M |
| **F34** | A function must be able to run for longer than a typical web request, subject to a timeout configured per function. | M |
| **F35** | A calling service must be able to pin the version of the function it invokes, so that a later deployment does not change its behaviour without the caller's knowledge. | M |
| **F36** | When the platform cannot serve a request, it must fail quickly and explicitly, so that a calling service can fall back rather than wait. | M |
| **F37** | A function should be able to write its output directly to our object storage as well as return it to the caller. | S |

---

## 7. Non-functional requirements

These carry equal weight to section 6, and several of them are the basis on
which the options in section 3 were rejected.

| | |
| --- | --- |
| **N1** | The platform must share no code, database or deployment path with any production service, and must not constitute an additional service in our estate. |
| **N2** | Its complete failure must have no effect on `localoy.app` beyond the degradation described in section 2.1, and we will verify this by stopping it during business hours. |
| **N3** | It must be possible to relocate it to different hardware without redesigning it. |
| **N4** | One function must not be able to access another function's code, data or configuration. |
| **N5** | One function must not be able to exhaust the host and affect the availability of others. |
| **N6** | Traffic must be encrypted in transit, passwords must not be stored recoverably, and secrets must be encrypted at rest so that the database alone is insufficient to recover them. |
| **N7** | Deployed code must execute with the minimum privilege required, and administrative operations must be restricted by role. |
| **N8** | The supplier must document the trust boundary accurately, including what is gained by compromising each component. |
| **N9** | The platform must make no third-party request and transmit no telemetry while running, and it must remain functional with outbound internet access blocked. |
| **N10** | All data must remain on our hardware, and the submissions of an identified individual must be locatable and deletable on request. |
| **N11** | Overhead on a request to a running function must be negligible, and the start-up delay for an idle function must be imperceptible to a user and removable where we require it. |
| **N12** | Per-request timing must be available from the response itself, so that N11 can be verified rather than assumed. |
| **N13** | The platform must support the load described in section 5 on the hardware described in section 5. |
| **N14** | It must restart unattended after a host reboot, with deployed functions intact. |
| **N15** | A complete backup must comprise a short and documented set of items, and restoration onto replacement hardware must be demonstrated to us before acceptance. |
| **N16** | Anything that cannot be recovered if lost must be identified explicitly in the documentation. |
| **N17** | A product engineer unfamiliar with the platform must be able to deploy an endpoint from the supplied documentation without assistance, and we will assess this at acceptance. |
| **N18** | The interface must be usable on a mobile device for logs and status, and error messages must indicate the corrective action required. |
| **N19** | Each routine operational task must be a single documented command, no task may presume a dedicated platform specialist, and an upgrade must not require existing functions to be redeployed. |
| **N20** | It must run on a standard Linux server with no dependency on a hosting provider, contain no licence check, key server or remote disablement mechanism, and introduce no recurring cost. |
| **N21** | Compression of a typical 5 MB image must complete within two seconds, and colour extraction from a stored image within one second. |
| **N22** | Unavailability of the platform must degrade a calling service rather than break it. We will verify this by stopping the platform and exercising an upload path that depends on it. |

---

## 8. Exclusions

The following are outside the scope of this engagement. We are not asking for
any modification to our production services, noting that a function requiring
data from one will call that service's interface as an ordinary client. We are
not asking for the migration of functionality that currently resides in those
services, for the front-end of any form or survey, or for multi-region
deployment and automatic failover. Section 2.1 does place the platform on a
production path, and we accept that exposure on the basis that calling services
degrade rather than fail, as required by F36 and N22, rather than by requiring
high availability of this platform. We do not require support for more than one
programming language in the first delivery.

---

## 9. Evaluation and required responses

We will assess proposals in the following order. All six constraints must be
satisfied. Every **M** requirement must be met, and the proposal must state
clearly which **S** requirements are included. Limitations must be stated
accurately, and a proposal that identifies no weaknesses will be treated as one
that has not examined them. The result must be suitable for operation by our own
team. We will then consider the time to a first usable version, where a narrower
delivery in two months is preferred to a complete one in six, and finally cost.

Please answer the following directly.

1. Which language will functions be written in, and why is it appropriate here?
2. What precisely must the host machine be trusted with?
3. What is the outcome of a deployment that fails part-way through?
4. What is the first constraint we will encounter as usage grows, and at what
   point will we reach it?
5. What would we have to do ourselves if the supplier ceased to be available?
6. Which of the requirements above do you consider to be incorrect?
