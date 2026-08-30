# Commons, the site

The marketing page for [Commons](https://github.com/sohamwas/commons), deployed to Vercel.

This is an **orphan branch**. It shares no history with `main` and is not part of the
product, so cloning Commons does not drag a marketing page and 300KB of screenshots along
with it. Nothing here is imported by the gateway or the dashboard.

    index.html   the whole page: markup, styles and one small script
    fonts/       Geist and Geist Mono, latin subset, self-hosted
    *.png        captures of the running dashboard

Static. No build step, no framework, no dependencies.

## Screenshots

`call-detail.png` and `rules.png` are real captures of the dashboard, not mockups, taken
against a run with the sample customer list.

**Recapture only from synthetic data.** These images carry whatever is on screen, and a
capture taken against a live merchant install would put real customer names, phone
numbers, emails and order ids into a public git history, where they are very hard to
remove. That is the one genuine risk in this branch, and it is a process rule rather than
something the code can enforce.
