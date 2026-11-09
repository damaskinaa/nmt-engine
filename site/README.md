# Groundwork landing page: setup (about 20 minutes)

## 1. Before going live, edit 3 things in `index.html`

- **Privacy notice** (footer): replace `[Your name or company]`, `[contact email]` and
  `[Netlify / Formspree]`.
- **Name:** "Groundwork" is a working name. Check that it and the domain are free, or
  find-and-replace it.
- **Analytics (optional but recommended):** create a free trial at plausible.io (EU-hosted and
  cookieless, so no cookie banner is needed). Add your domain, then uncomment the script line in
  `<head>` and put your domain in it.

## 2. Host it (free)

**Netlify (recommended, the form works with no extra setup):**
1. Go to app.netlify.com → Add new site → Deploy manually.
2. Drag the `site` folder onto the page.
3. Site settings → Forms → enable form detection, then deploy once more (drag the folder again).
4. Submissions appear under Forms → `sample-request` (email + market + variant + source) and
   `price-answer`. Turn on email notifications there.

**Anywhere else (GitHub Pages, Framer embed, …):** create a free form at formspree.io and paste
its URL into `FORM_ENDPOINT` at the top of the `<script>`.

## 3. Test before sharing

Open the live page, submit your own email, and check that it arrives in Netlify Forms. Then
delete the test entry.

## 4. Links to share

The page picks one of the 3 headlines at random and remembers it per visitor. To check a
specific one: `?v=a` (speed), `?v=b` (proof), `?v=c` (kill early).

Tag each channel so you can compare them: `https://YOUR-SITE/?utm_source=linkedin`. Use one
channel for the test.

## 5. Reading the result (pass rule from file 11, T4)

| Measure | Where | Pass |
|---|---|---|
| Visitors | Plausible | about 200 founders or PMs |
| Click rate | Plausible event "CTA click" ÷ visitors | ≥ 5% |
| Emails | Netlify Forms → sample-request | ≥ 3 |
| Winning headline | requests per variant | tells you the top criterion of your segment |
| Price | price-answer: yes/maybe/no at €49 vs €149 | first willingness-to-pay signal |

Without Plausible you can still count emails and see the variant on each request, but not the
click rate.

## 6. What happens after someone signs up

Each person gets a real report within 3 working days, assembled by hand from public sources
until the engine is ready (file 12, "Delivering the first reports"). Afterwards, ask them: "At
what exact moment in this report were you pleasantly surprised?"
