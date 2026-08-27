# KS State Civics Live Demo Output

Generated against the existing Docker cell `exais-vector-store-ks-state-civics` on 2026-08-13.

- API container image digest in use: `sha256:197f120123d5a5738825730e5d0f0b85042f5a9ad298014401ef7a31675289e2`
- Vector store: `vs_a0d3ac76893e4f6f83bf2992`
- Endpoint tested: `/v1/vector_stores/{vector_store_id}/search`
- Readiness after clearing stale Postgres sessions: `{"ready":true,"db":true,"qdrant":true}`

Plain-English description:

> This is a private Kansas court-decision research store. It lets an agent ask legal or civics questions and retrieve the most relevant Kansas appellate decisions with case title, docket number, court, decision date, score, snippet, and source PDF.

Important boundary: this is retrieval output, not legal advice. A lawyer still reviews the cited opinions.

## Example 1: Mistake Of Law Defense

Question:

> Can a Kansas criminal defendant rely on an official interpretation of a statute as a mistake-of-law defense?

Live search time: `1482.5 ms`

Top hits:

1. `State v. Harris`, docket `116515`, Court of Appeals, `2020-07-17`, score `1.0`
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/11c9dded-0908-4f18-8f1b-3207781f331d_116515_2020717_00.pdf`
   - Why it is useful: Directly discusses reliance on an official interpretation of a statute and Harris' pocketknife mistake-of-law defense.

2. `State v. Harris`, docket `116515`, Court of Appeals, `2018-01-19`, score `0.90076`
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/39831f47-7fd6-4a88-b69f-6de03ee80ed1_116515_20180119_09.pdf`
   - Why it is useful: Finds the related Harris appeal discussing Department of Corrections guidance and the parole officer's advice.

## Example 2: K.S.A. 60-1507 Procedural Bar

Question:

> Which Kansas cases discuss ineffective assistance of counsel in K.S.A. 60-1507 motions, untimely or successive motions, and manifest injustice?

Live search time: `1418.9 ms`

Top hits:

1. `Denney v. State`, docket `126784`, Court of Appeals, `2024-08-09`, score `1.0`
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/248975b1-6640-4817-b5c4-e8d877f06ae4_126784.pdf`
   - Why it is useful: Addresses repeated 60-1507 motions and time-limit arguments.

2. `Elliott v. State`, docket `124402`, Court of Appeals, `2022-07-29`, score `0.951913`
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/ccb7ce63-e839-47dd-a707-2e76d3697b28_124402.pdf`
   - Why it is useful: Finds a 60-1507 appeal involving ineffective assistance claims.

3. `Conley v. State`, docket `111777`, Court of Appeals, `2015-11-20`, score `0.950263`
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/ffc02a3a-8019-44cd-afda-e5ad92690cac_111777.pdf`
   - Why it is useful: Returns authority on successive 60-1507 motions and exceptional-circumstances analysis.

## Example 3: Kansas School Finance

Question:

> What Kansas Supreme Court decisions discuss school finance, Article 6, adequacy, equity, and legislative remedy?

Live search time: `1579.0 ms`

Top hits:

1. `Gannon v. State`, docket `113267`, Supreme Court, `2016-05-27`, score `1.0`
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/18546c08-9689-4309-9c83-066effcbe841_113267_4.pdf`
   - Why it is useful: Finds a Gannon order addressing school-finance inequities and legislative remedy.

2. `Gannon v. State`, docket `113267`, Supreme Court, `2016-06-28`, score `0.993699`
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/2a775d30-aebb-4b90-a19e-8890961057b0_113267_628.pdf`
   - Why it is useful: Finds the special-session follow-up order in the same school-finance litigation.

3. `Gannon v. State`, docket `113267`, Supreme Court, `2016-02-11`, score `0.983892`
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/81dffb63-087e-4e75-b0b4-b641b9cfee99_113267_6.pdf`
   - Why it is useful: Finds earlier remedial analysis in the Article 6 school-finance sequence.

## Example 4: Kansas Open Records Act

Question:

> Which Kansas cases discuss Kansas Open Records Act law-enforcement investigatory records, privacy, and exemptions?

Live search time: `1281.8 ms`

Top hits:

1. `Seck v. City of Overland Park`, docket `84340`, Court of Appeals, `2000-12-22`, score `1.0`
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/a99b45e8-48f3-450d-8662-05a138ceec17_84340_20001222_01.pdf`
   - Why it is useful: Directly addresses the Kansas Open Records Act criminal-investigation exception.

2. `Wichita Eagle & Beacon Publishing Co. v. Simmons, Secretary of Corrections`, docket `87374`, Supreme Court, `2002-07-12`, score `0.948252`
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/02795177-aa54-423d-8f6c-9e35194b9fc6_87374_20020712_01.pdf`
   - Why it is useful: Finds a Supreme Court KORA dispute involving corrections records.

3. `Hunter Health Clinic v. Wichita State University`, docket `111586`, Court of Appeals, `2015-11-06`, score `0.923204`
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/8a9e3ade-6200-4936-8336-be9e55502e17_111586.pdf`
   - Why it is useful: Returns public-records policy language and disclosure analysis under KORA.

## Example 5: Termination Of Parental Rights

Question:

> Which Kansas cases discuss termination of parental rights, unfitness, best interests, reintegration plans, and clear-and-convincing evidence?

Live search time: `1146.3 ms`

Top hits:

1. `In re P.B.`, docket `123625`, Court of Appeals, `2021-08-13`, score `1.0`
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/833aa7ee-415b-4007-8d60-cdacea32a50b_123625.pdf`
   - Why it is useful: Finds a termination appeal in the child-in-need-of-care context.

2. `In re C.H.`, docket `123640`, Court of Appeals, `2021-10-22`, score `0.986846`
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/7520c398-d2bc-4a95-82ed-64c51ba352d1_123640.pdf`
   - Why it is useful: Retrieves facts around parental progress, assigned tasks, and reintegration issues.

3. `In re L.B.`, docket `102202`, Court of Appeals, `2009-10-16`, score `0.972427`
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/33780aa7-312f-4f39-a927-d1b85692fa68_102202.pdf`
   - Why it is useful: Finds appellate-procedure language tied to findings of unfitness and termination orders.

