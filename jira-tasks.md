## Task 1 — PoC Concept Definition

### Description

Define the concept and scope of the PoC AI Agent. Identify the problem to solve, expected users, key capabilities, and why this PoC is meaningful. Prepare a short overview to present during the next weekly sync.

### Scope

- Specify the PoC idea and target user scenario. **For this run, limit the scope to a chatbot over structured and/or unstructured data — preferably SQL as the data source.**
- Describe the problem statement and expected value.
- List planned AI capabilities and interactions with the chosen platform.
- Define data inputs, tooling needs, or integrations.
- Prepare a short concept presentation (3–5 minutes).
- Prepare data (SQL).

### Acceptance criteria

- Written concept uploaded to Jira.
- Concept presented during the weekly update.

### PoC examples (for inspiration)

- Chatbot for a car-selling dealer (include dummy data or scraped data from sample dealer pages).
- Chatbot as a banking pattern analyzer (payment patterns in mortgage context, budget overspends, etc.).

### Reference datasets

**Structured data (SQL / CSV / Excel):**

- **Tickets / Incidents** — `TicketId`, `CreatedDate`, `Category`, `Priority`, `AssignedTeam`, `ResolutionTime`, `Status`
- **Sales Orders** — `OrderDate`, `Customer`, `Product`, `Region`, `Amount`
- **Employee Skills / Training Records** — `Employee`, `Skill`, `Level`, `LastUsedDate`

**Unstructured data:**

- PDFs: policies, manuals, incident post-mortems
- Markdown / Word docs: retrospectives, meeting notes
- Plain text: customer feedback, chat transcripts

### Expected chatbot capabilities

The bot should answer:

- **Fact-based questions** — *e.g.* "What is our refund policy?"
- **Data questions** — *e.g.* "How many high-priority incidents happened last month?"
- **Mixed questions** — *e.g.* "Based on incident reports and ticket data, what are the most common root causes?"

### Sample structured data (CSV, ticket import-ready)

```
Timestamp,system_name,component,log_level,corr_id,user_ID,message
2025-05-01T00:04:59+00:00,casb-proxy-01,CASB,WARN,7de471bf-f865-4d61-8515-5381e4dc6680,SUPERUSER,Inactive Box OAuth grant for eroberts not revoked — 5 days since last use
2025-05-01T00:11:57+00:00,vuln-scan-01,Vulnerability_Scanner,INFO,ad6853c6-4cd3-46a4-9fc0-8086228ba68a,ADMIN,Asset WKSTN-117 (172.16.254.3) added to scan scope — first scan scheduled
2025-05-01T00:34:30+00:00,pam-vault-01,PAM,INFO,caf3c094-b61e-48af-8ad7-6a0d52194d62,STANDARDUSER,User glopez checked out credentials for SRV-APP-02 from VAULT-PROD-01 — session initiated
2025-05-01T00:49:26+00:00,casb-proxy-02,CASB,ERROR,31286dc8-40b1-4b20-99eb-b4955d7ecb5f,ADMIN,Threat score enrichment service unreachable — 15 CASB decisions made without TI context
```

---

## Task 2 — PoC Development: Skeleton & Core Functionality

### Description

Design and implement the PoC based on the selected idea. Start by creating the project skeleton, then iteratively add meaningful functionality (tools, data retrieval, reasoning flows, integrations).

Throughout the development cycle, prepare and deliver weekly 3–5-minute progress updates during demo sessions. Each update should include completed work, challenges, and next steps.

### Scope

- Build the initial structure of the PoC.
- Incrementally extend the PoC with meaningful capabilities relevant to the chosen use case.
- Share progress in short weekly updates — built work, key improvements, next development goals.

### Acceptance criteria

- Weekly progress updates consistently delivered, summarizing achievements, challenges, and next steps.
- Jira story updated weekly with a progress summary and any blockers.

---

## Task 3 — Final PoC Demo

### Description

Present the completed PoC: walk through the architecture, demonstrate functionality, and share lessons learned.

### Acceptance criteria

- Demo accepted and code available in the repository.
- Demo no longer than 5 minutes.

