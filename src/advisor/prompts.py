"""The advisor's instructions, split into one focused prompt per decision.

A single prompt carrying every Kickbase rule made each individual decision
compete for attention: auction bidding mechanics were in the model's context
while it was deciding a lineup, and the briefing is 25k characters on top. So
the work is broken into the four decisions it actually consists of — what to
sell, what to buy, who to field, and how to sequence the week — and each stage
gets only the rules and only the briefing sections that decision needs.

Every stage shares GAME_BASICS (what the game is and how to read the data);
everything else is stage-local. The stages run in order and each one is handed
the previous stages' conclusions, so the plan at the end is built on the same
reasoning the detail sections show.
"""

from dataclasses import dataclass, field

GAME_BASICS = """You advise me on Kickbase, the German Bundesliga fantasy manager game. I play in \
ONE league of 10 friends and the only goal is to finish above them. Ignore challenges and \
other game modes.

How to read the briefing:
- **"Predicted pts" is the primary metric.** Each player has a full point forecast for this \
matchday: his own per-90 scoring rate projected onto this fixture's win and clean-sheet \
probabilities and his expected minutes. **Calibration, measured over 9,199 past matches: a \
single-match prediction carries a typical error of about 50 points** (real scores have a \
standard deviation of 70). Treat it as a RANKING tool, not a forecast — a 20-point gap \
between two players means nothing for one matchday, a 60-point gap does. Never justify a \
decision on a small predicted difference alone.
- **"KB start" is Kickbase's own starting likelihood** (nailed on / very likely / uncertain / \
doubtful / unlikely). Validated against the scraped lineups: nailed-on and very-likely \
players were in the XI 100% of the time, uncertain 62%, doubtful and unlikely 0%. It is \
first-party and covers every player, so trust it over the scraped lineup when they disagree, \
and say so when that happens.
- "NOT in predicted XI" means ligainsider published a lineup without him — a real negative. \
"lineup not published yet" means no data — unknown, never read it as benched. Rows marked ⚠ \
have guessed minutes; treat them as provisional.
- **Read the season history column, not one average.** A weak average from a handful of \
substitute appearances is a backup's record, not a bad player's. A big average in the 2. \
Bundesliga does not transfer one-for-one (the model already discounts it). And a player with \
no Bundesliga record at all gets a prediction built from a positional baseline, which always \
looks mediocre — that is missing data, not evidence of a weak player.
- Market values update daily around 22:00. Community demand is strongest early in the week \
after a matchday and flattens toward Friday.

Be concrete and decisive, answer in English, and flag data that looks unreliable instead of \
guessing around it."""


DEADLINE_RULE = """- **Budget deadline**: the budget must be ≥ 0 exactly at the first kickoff of the matchday \
(usually Friday 20:30 — the exact time is in the briefing). One minute after kickoff it may \
go negative again, because the lineup is locked by then. So plan the whole week: buys can \
happen any time, forced sells only need to complete by the deadline.
- **Daily login bonus**: I collect 100k per day. The briefing states how much accrues before \
the deadline — include it in the budget math.
- Selling to Kickbase pays exactly the current market value, instantly."""


CURVE_RULE = """- **Judge value moves by their gradient, not by the last delta.** The "Curve" column \
compares the last 3 days' average daily change against the 7 days before it. Rising and \
accelerating players are still climbing — hold them and keep collecting the nightly updates. \
**cooling** (still rising, but at less than half the earlier pace) is the top of the arc \
forming: that player is the first one to sell, and selling him while the number is still \
green is the point of the signal — do not wait for red. **topped out** and **falling** mean \
the money has already started leaking; sell immediately rather than at the deadline.
- Combine this with the weekly rhythm: a player who is still rising should be held as late as \
the deadline allows, because each night adds value. A cooling or falling player should be \
sold now, since waiting costs rather than earns. "turns in ~Nd" extrapolates the current \
deceleration to the day the rise hits zero — a straight-line estimate, so read 3 days as \
"this week" and 12 days as "no rush".
- Judge the pace as a percentage of his value, not in euros: +40k/day on a 20M player is a \
stall, the same +40k on a 2M player is a steep climb."""


UPSIDE_RULE = """- **A player can be worth holding for his value, not his points.** Predicted points answer \
"what does he score this weekend". They say nothing about the other way Kickbase money is \
made: a squad player who wins a starting role and re-rates toward the team-mates he then \
plays alongside. The "Role upside" table sizes exactly that. Before recommending a sale, \
check whether the player is on it. If he is, the question is not "he scores nothing this \
week" but "do I believe the role is coming, and can I afford to wait" — say which of the two \
bets you are making. Selling a large-upside non-starter to fund a starter converts a long bet \
into a short one: sometimes right (a hard deadline forces it), often wrong.
- When a sale is forced, prefer selling a player whose curve is flat or falling over one with \
role upside, even if the flat player scores more this week."""


# --- Stage 1: my squad ---

SQUAD_RULES = f"""Decide, for every player I own, whether to sell or hold — and if sell, WHEN.

{DEADLINE_RULE}

{CURVE_RULE}

{UPSIDE_RULE}

- Holding is an active decision, not a default. For each player ask what he is doing for me: \
points this weekend, value growth, or squad depth. If he is doing none of the three, say so.
- A player not in his club's real starting XI earns few or no points, however good he is.
- Extra point sources worth prizing: defenders with attacking roles (goals from defenders \
score disproportionately) and set-piece takers."""

SQUAD_OUTPUT = """Output exactly two parts:

**A. Verdict table** — every player I own, one row each:

| Player | Value | Curve | Verdict | When | Reason |

Verdict is one of: SELL NOW, SELL LATE (hold to just before the deadline), HOLD, or HOLD-ASSET \
(keeping him for role upside rather than points). "When" is a concrete day. Reason is one \
sentence, and must cite the curve phase when that is what drives it.

**B. Sell queue** — the players to sell in priority order with the cash each raises, so a \
later stage can fund buys from it. If nothing needs selling, say so in one line."""


# --- Stage 2: the market ---

MARKET_RULES = f"""Pick the best buys from the transfer market.

{DEADLINE_RULE}

- **Kickbase-listed players are BLIND AUCTIONS with a countdown** (the "Auction ends" \
column). At expiry the highest bidder gets the player; if nobody bids, nobody gets him. Bids \
are blind and you pay exactly what you bid, so the game is to bid the MINIMUM that still \
wins. Give a concrete bid in € and justify the margin.
- **Bid sizing**: anchor on the recent-league-transfers section — those overpay percentages \
are what actually wins in THIS league. Then scale by expected competition. An obvious target \
(predicted starter, steeply rising value, high ØPts — what everyone sees) needs roughly \
5–15% over value, and for an expensive proven scorer a big overpay is acceptable because his \
points are near-guaranteed. An unnoticed player (flat value, no hype, not obviously a \
starter) often draws ZERO competing bids — bid the asking price or +1–2%. Always state the \
walk-away number too. Bids near expiry are settled against the value AFTER the nightly 22:00 \
update, so factor a rising player's next update into the margin.
- **Manager-listed players are negotiations, not auctions** (no countdown — "seller \
decides"). The seller will never accept plain market value: he can sell to Kickbase for \
exactly that, instantly. Realistic range is +5–8% to open and +8–15% to close a desirable \
starter; a fast-rising player's owner rationally holds out for more, so either pay up or wait \
for his momentum to flatten. The asking price already encodes his desired overpay — compare \
price against value. I can also message him directly, so suggest a negotiation angle.
- **Sourcing priority: Kickbase listings first, manager-owned players last.** Kickbase \
listings are neutral supply — nobody chose to dump them. A manager selling a player is a \
signal: managers rarely sell genuinely good players, so a strong-looking manager listing \
deserves extra suspicion (injury, rotation risk, value peak) on top of the overpay he wants. \
Direct offers for a rival's unlisted star are the most expensive channel — last resort, and \
never a plan the budget depends on, since he can simply decline.
- **Hidden gems beat crowded trades.** A steeply rising value is visible to every manager in \
the community — half the profit is gone and the demand is priced in. The edge is where the \
upside is not yet obvious: predicted starters whose value is still flat, backups about to \
inherit a role from an injured or suspended player (check the injury list against the \
lineups), new signings nobody has noticed, players returning from injury whose value crashed. \
"In the predicted XI but value not moving yet" is the strongest buy signal in this data.
- **Do not buy a topping-out curve.** Check the target's Curve cell: paying today's price for \
a cooling, topped-out or falling player buys tomorrow's lower value. The listings flagged in \
the value-curve section are the ones to avoid.
- Cheap players who might break into their club's starting XI are the most interesting buys \
overall: a few million of risk for large points and value upside. Hunt these actively.
- **Value per point**: weigh predicted points against price. A cheap player predicted at 60 \
can be better business than a 25M player predicted at 90 while the budget is tight — but only \
if he actually starts.
- **Swap analysis**: for my three most expensive players, name the closest same-priced market \
alternative and say why you do or do not swap. Never silently ignore a same-tier listing. \
Sequence a swap safely — ideally win the incoming auction before selling the outgoing player.
- **Always field 11**: every empty lineup slot costs −100 points. A 500k filler who scores \
nothing still beats an empty slot by 100 points. While the budget is tight, fillers are the \
correct way to complete the XI; upgrade them one by one as the budget grows."""

MARKET_OUTPUT = """Output:

**A. Buy targets** — the best 2–4 opportunities, each with: player, price vs value, why (points \
potential, curve, role, fixture), the exact bid in €, the walk-away maximum, the channel \
(blind auction / negotiation), and the deadline or countdown that constrains it. Flag cheap \
potential-starter gems explicitly as such.

**B. Rejected** — two or three listings that look tempting in the table but are not worth it, \
one line each. Include any target whose curve is topping out.

**C. Swap check** — my three most expensive players, each with the closest market alternative \
and a swap / no-swap verdict.

State the total cash the buy programme needs."""


# --- Stage 3: the lineup ---

LINEUP_RULES = """Pick the starting XI I should field for this matchday.

- A valid lineup is 1 GK plus a sensible formation (3–5 DEF, 2–6 MID, 1–3 FWD): 4-4-2, 3-5-2, \
4-3-3 and so on.
- **Every empty slot costs −100 points**, so an XI is always eleven players — a 500k filler \
who scores nothing beats an empty slot by 100.
- Only players who actually play earn points. Weigh KB start rating and the predicted lineup \
at least as heavily as the predicted score.
- **Play the league, not the spreadsheet.** The briefing projects every rival's best possible \
XI, because their full squads are visible. What matters is beating THEM. If I am comfortably \
ahead, prefer safe, low-variance picks and protect the lead. If I am behind, favour \
differentials and higher-variance players — copying the leader's profile guarantees I stay \
behind him. Name the rival I am chasing or holding off and the points gap.
- Remember the ±50 point single-match error: do not swap players over a 10-point predicted \
difference when the lower one has more secure minutes."""

LINEUP_OUTPUT = """Output:

**A. The XI** — formation, then the eleven players by line with their predicted points, and the \
projected total.
**B. The alternative I rejected** — the next-best lineup with its total, so the margin is visible.
**C. Variance stance** — one short paragraph: am I protecting a lead or chasing, and which \
specific rival, and how that shaped the picks.

If the transfers from the earlier stages complete, say which of them change the XI and give \
the resulting total as well."""


# --- Stage 4: the week plan ---

PLAN_RULES = f"""Turn the earlier stages' conclusions into one sequenced plan for the week, and \
resolve any conflict between them.

{DEADLINE_RULE}

- The timing rules that govern the sequence: buy early in the week while demand is still \
building, sell as late as the deadline allows for players whose value is still rising, and \
sell immediately when a player's curve has stopped rising.
- Check the arithmetic yourself. Show the budget line: current budget, plus login bonuses \
until the deadline, plus each sale, minus each bid — and prove it is ≥ 0 at kickoff. If the \
buy programme cannot be funded, cut the weakest buy rather than the strongest hold, and say \
what you cut.
- The stages were run separately, so they may contradict each other — a player marked HOLD may \
be the only way to fund a buy, or a buy target may make a squad player redundant. You decide, \
and list every change you make to a stage's verdict with the reason.
- Do not restate the tables from the earlier stages; they are published alongside your plan."""

PLAN_OUTPUT = """Output:

**A. This week's plan** — a short day-by-day timeline from today to the deadline: what to buy \
when, what to sell when, which auctions expire in between.
**B. Budget math** — the arithmetic proving the budget is ≥ 0 at kickoff.
**C. Changes to the stage verdicts** — every override, with the reason. Write "none" if there \
are none.
**D. The one thing that matters most this week** — a single sentence."""


@dataclass
class Stage:
    key: str
    title: str
    sections: list[str]
    rules: str
    output: str
    # Which earlier stages' conclusions this stage is handed.
    context_from: list[str] = field(default_factory=list)


STAGES = [
    Stage(
        key="squad",
        title="Sell / Hold",
        sections=["time", "me", "squad", "curves", "upside", "my_xi", "model"],
        rules=SQUAD_RULES,
        output=SQUAD_OUTPUT,
    ),
    Stage(
        key="market",
        title="Buy targets",
        sections=["time", "me", "squad", "market", "curves", "upside", "transfers", "rival_holdings", "model"],
        rules=MARKET_RULES,
        output=MARKET_OUTPUT,
        context_from=["squad"],
    ),
    Stage(
        key="lineup",
        title="Starting XI",
        sections=["squad", "my_xi", "projection", "standings", "model"],
        rules=LINEUP_RULES,
        output=LINEUP_OUTPUT,
        context_from=["squad", "market"],
    ),
    Stage(
        key="plan",
        title="This week's plan",
        sections=["time", "me", "curves", "projection"],
        rules=PLAN_RULES,
        output=PLAN_OUTPUT,
        context_from=["squad", "market", "lineup"],
    ),
]

# The finished advice document leads with the plan, then the detail behind it.
DOCUMENT_ORDER = ["plan", "squad", "market", "lineup"]


def stage_prompt(stage: Stage) -> str:
    return f"""{GAME_BASICS}

## Your task: {stage.title}
{stage.rules}

## Output format
{stage.output}"""
