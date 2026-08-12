# Flux.ai Community Feedback Analysis
*Compiled August 12, 2026 · Sources: Reddit (via Arctic Shift archive), Hacker News (Algolia), Trustpilot, G2, Product Hunt, EEVblog, GroupDIY, All About Circuits forum, trade press, YouTube, Flux blog/docs*

## TLDR

The product improved substantially through 2025–2026, but community sentiment collapsed over the same period. The conversation shifted from "is the AI good?" (2023–24) to "is this company legitimate?" (2025–26), driven by the metered ACU billing model and capped by the Adafruit legal dispute (June 2026). Trustpilot: **1.6/5, 84% one-star**. Consistent technical verdict across eras: strong schematic-side assistant, unreliable finisher — placement/routing collapses beyond simple boards. The community's standard advice is now *"use Claude and KiCad instead."*

## Sentiment timeline

| Era | Sentiment | Dominant theme |
|---|---|---|
| 2021 | Dismissive (pros) | Dave Jones/EEVblog: browser EDA "a solution to a problem that doesn't really exist" |
| 2023 (Copilot launch) | Curious skepticism | Hallucinated 555 values, missing USB-C termination; editor lag; "interesting but beta" |
| 2024 | Mixed | Editor maturity complaints (broken collab, unusable tracing); experienced EEs bounce to KiCad; astroturf suspicion grows |
| Oct 2025 (agentic + ACU pricing) | Inflection down | Metered credits + default $100 auto-top-up converts "immature tool" into "scam" narrative |
| Jun 2026 (Adafruit dispute) | Collapse | CFAA/defamation demand letter over disclosure of hardcoded user counters + exposed Firebase key; Adafruit sues; 684-pt HN thread, zero product defenders |

## What people like

- **Datasheet Q&A / part selection** — most consistently praised AI feature across all eras and skill levels; even critics concede it
- **Schematic-stage agent work** — architecture proposals, block wiring from datasheets; JLCPCB hands-on: schematic work "10 hours → ~2 hours"; agent "behaves like a junior hardware engineer"
- **Platform concept** — browser collaboration, versioning, forking, 3D view on phone, live pricing from 6 distributors in-editor
- **Named support humans** (Kerry, Nico, Eli) — praised even by critics
- **Beginner empowerment** — "It makes me _feel_ like [a hardware engineer]"; some real fabbed boards shipped by hobbyists

## What people dislike

1. **Billing (dominant theme by volume, 2025–26)**
   - ~$6–7/agent prompt; cost known only after the run; agent "uses all your credits to rectify its own mistakes"
   - Auto top-up **on by default at $100–200**; strings of automatic $20 charges; Flux replies admit the default "shouldn't be set at $100"
   - Trial-conversion charges, post-cancellation billing, deletion requiring unanswered tickets; routine losses $40–$400, outliers >$1,000; chargebacks and FTC complaints reported
2. **Layout quality** — "grinds tokens for little return"; unusable placement past ~20 components; impossible BGA fanout on Flux's own showcase board; demo video allegedly shorted a power rail; 180-component test: "Copilot CANNOT place components"
3. **Company trust** — Adafruit SLAPP reaction; campaign UTM parameters found in supposedly organic positive Reddit posts; 5-star Trustpilot cluster right after profile claimed; ad saturation
4. **Professional indifference** — no major EE YouTuber ever reviewed the agentic version; Hackaday never covered it; r/PrintedCircuitBoard bans AI topics; cloud lock-in and no migration path are dealbreakers for pros

## Capability state (Aug 2026)

- **Agentic:** prompt → plan → parts (live pricing) → schematic → placement → routing; continuous ERC/DRC self-correction (Feb 2026); mid-run steering (May 2026); clarifying questions + Chat mode + voice + public MCP server (Aug 2026). ~900k agent runs claimed in first 4 months
- **Sweet spot:** 2–4 layer, ~40–100 components (even competitor Quilter concedes this range)
- **Editor:** 8 copper layers max; diff pairs + impedance from stackup; manufacturer DRC templates; via stitching
- **Simulation:** prompt-driven SPICE via ngspice (Mar 2026), 340k+ models
- **I/O:** Gerber/drill/BOM/PnP/IPC-D-356/STEP export; Eagle schematic + KiCad/Eagle/PADS part import; **no layout or Gerber import; no ODB++**
- **Company:** $37M raised Feb 2026 (8VC, Bain); claimed 1.1M users — the number the Adafruit dispute called into question

## Most painful limitations

1. **The last 20% of layout** — auto-placement officially an "80% starting point"; high-speed, length matching, strict layer rules officially out of scope; no length-tuning, panelization, rigid-flex
2. **Economics per working board** — agent meters while looping on its own mistakes; users report one Flux board costing more than a year of Claude + KiCad
3. **No migration path** — no layout/Gerber import in, redraw-only path out; cloud-only hosting
4. **Verification paradox** — output requires an experienced EE to validate, but the ad-driven target market is beginners who can't
5. **Reputational overhang** — billing reputation + Adafruit suit now actively deter signups ("saw the ad, searched Reddit, decided against it")

## Key sources

- HN: [Show HN 2023](https://news.ycombinator.com/item?id=36497019) · [Ultra Librarian 2024](https://news.ycombinator.com/item?id=39619196) · [Agentic launch 2025](https://news.ycombinator.com/item?id=45508424) · [Adafruit letter (684 pts)](https://news.ycombinator.com/item?id=48368121) · [Adafruit suit](https://news.ycombinator.com/item?id=48486411)
- Reddit: [Do not use flux.ai (r/KiCad)](https://reddit.com/r/KiCad/comments/1mf8z2r/) · [Billing traps (r/PCB)](https://reddit.com/r/PCB/comments/1t476x4/) · [Ad backlash (r/embedded)](https://reddit.com/r/embedded/comments/1re2vtm/) · [Adafruit letter (r/embedded)](https://reddit.com/r/embedded/comments/1turxyx/)
- Reviews: [Trustpilot 1.6/5](https://www.trustpilot.com/review/flux.ai) · [G2](https://www.g2.com/products/flux-ai/reviews) · [Product Hunt](https://www.producthunt.com/products/flux-10)
- Press: [Engineering.com "When it works, it's magical"](https://www.engineering.com/fluxs-electrical-engineering-ai-when-it-works-its-magical/) · [Electronics-Lab review](https://www.electronics-lab.com/flux-ai-an-ai-powered-browser-based-pcb-design-tool-review/) · [All About Circuits hands-on](https://www.allaboutcircuits.com/news/flux-upgrade-graduates-ai-assistant-ai-circuit-co-designer/) · [JLCPCB guide](https://jlcpcb.com/blog/how-to-design-a-pcb-with-fluxai)
- Competitor analyses (biased): [Quilter](https://www.quilter.ai/blog/the-2026-guide-to-autonomous-pcb-design-quilter-vs-deeppcb-vs-flux-ai) · [Altium](https://resources.altium.com/p/altium-designer-vs-flux-professional-pcb-projects)
- Flux primary: [blog](https://www.flux.ai/p/blog) · [pricing](https://www.flux.ai/p/pricing) · [$37M raise](https://www.flux.ai/p/blog/we-raised-37m-to-take-the-hard-out-of-hardware) · [Summer 2026 / MCP](https://www.flux.ai/p/blog/summer-2026-updates-flux-mcp-server-and-chat-mode)
