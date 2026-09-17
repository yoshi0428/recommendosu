Yes. I’d treat this as a **personalized difficulty-profile → candidate-map ranking** problem, rather than simply “find maps whose category matches the player.”

 The key distinction is:

 > **You don't want to recommend maps the player is already good at. You want maps whose difficulty profile is just beyond what the player currently converts well.**

 That changes how I’d use your classifier.

 ## 1\. Build a player skill profile from their plays

 Suppose your classifier outputs something like:

```
aim:    0.65
speed:  0.15
tech:   0.20
```

 for each map.

 For every play, you have:

 - map category probabilities
- star rating / difficulty
- accuracy
- combo / max combo
- misses
- pp
- mods
- score age (for recents)
- potentially score percentile / leaderboard position

 I would **not simply average the categories weighted by accuracy**.

 Instead, estimate:

 > “At what difficulty does this player perform well for each skill category?”

 For example, you might end up with:

 | Skill | Comfortable | Stretch | Poor |
| --- | --- | --- | --- |
| Aim | 6.2★ | 6.7★ | 7.2★ |
| Speed | 5.5★ | 6.0★ | 6.5★ |
| Tech | 5.8★ | 6.3★ | 6.8★ |

 That is much more useful for recommendations than simply saying “this player is 65% aim.”

 ### A useful formulation

 For a play $i$, let:

 - $x_i$ = map's category vector
- $d_i$ = difficulty
- $a_i$ = accuracy
- $m_i$ = miss rate
- $c_i$ = combo ratio
- $p_i$ = pp

 Then estimate something like:

 $$
P(\text{good play} \mid x_i, d_i, mods_i)
$$

 rather than merely learning:

 $$
P(\text{category} \mid player)
$$

 The former directly answers the recommendation problem.

---

 # 2\. Don't use raw accuracy as your only play weight

 Accuracy is useful, but **accuracy alone is misleading**.

 A 99% on a 4★ map doesn't tell you nearly as much as a 96% on a 7★ map.

 And conversely, raw pp already incorporates difficulty, accuracy, combo, misses, etc. The official pp system is explicitly intended to represent performance relative to map difficulty.  osu!

 So I would use **pp as one signal**, but not literally as:

```
play_weight = pp
```

 because you're right about recent plays.

 ## I would separate two concepts

 ### Skill evidence

 “How good is this play evidence?”

 Use something closer to:

```
skill_weight =
    difficulty_signal
  × performance_signal
  × recency_signal
```

 where `performance_signal` might incorporate:

 - accuracy
- miss rate
- combo %
- pp relative to the map's difficulty
- possibly percentile

 ### Recommendation intent

 “How much do we care about this play when deciding what the player wants to play now?”

 That's where recency belongs.

 For example:

```
top play weight:     1.0
recent play weight:  0.3–0.7
```

 rather than making recent plays intrinsically weaker because their pp is lower.

---

 # 3\. I'd actually normalize pp before using it

 A particularly useful feature would be something like:

 $$
\text{performance ratio}
=
\frac{\text{play pp}}{\text{expected pp at that difficulty}}
$$

 or, even better, compare against a population distribution.

 For example:

```
Player A:
7.0★ map → 260 pp
```

 and

```
Player B:
5.5★ map → 220 pp
```

 Raw pp says A is better.

 But for **personal modeling**, you care about how unusually good that play was relative to the player's existing ability.

 You could therefore transform the play into something like:

```
difficulty = 7.0★
performance percentile = 92%
```

 That is much more useful.

 If you have enough data, I'd train a model to predict expected accuracy / pp as a function of:

```
difficulty
category
mods
map length
```

 and then use the **residual**:

 $$
r_i = actual\_performance_i - expected\_performance_i
$$

 A play with a large positive residual is strong evidence that the player is particularly good at that kind of map.

---

 # 4\. Top plays and recent plays should have different meanings

 This is important.

 ### Top plays answer:

 > **What is this player capable of?**

 ### Recent plays answer:

 > **What is this player currently working on / enjoying / warming up to?**

 So I'd build **two player profiles**.

 ### Long-term profile

 Use top plays, perhaps the best 50–100.

 This gives you:

```
capability:
aim      0.82
speed    0.53
tech     0.64
reading  0.71
```

 ### Current profile

 Use recent plays, perhaps last 20–50, with strong recency decay.

```
current activity:
aim      0.60
speed    0.81
tech     0.55
reading  0.70
```

 Then combine them:

 $$
P_{player} =
\alpha P_{longterm} + (1-\alpha)P_{current}
$$

 with perhaps:

```
α = 0.7
```

 But **I'd make α adaptive**.

 If the player has recently played 30 speed maps, that's strong evidence that they are currently interested in speed. You want your recommender to notice that.

---

 # 5\. Your classifier becomes especially useful here

 Suppose your classifier gives each map:

```
Aim      0.70
Speed    0.10
Tech     0.15
Reading  0.05
```

 Instead of recommending based on cosine similarity alone, calculate how that map intersects with the player's **strength/weakness frontier**.

 For example:

```
Player capability

Aim       █████████░ 0.90
Speed     ██████░░░░ 0.60
Tech      ███████░░░ 0.70
Reading   ████████░░ 0.80
```

 A map that's:

```
Aim 0.7
Speed 0.1
Tech 0.15
```

 probably isn't very interesting—it overlaps heavily with an existing strength.

 But:

```
Aim   0.45
Speed 0.40
Tech  0.15
```

 might be excellent if the player's aim is strong but speed is just below their current ceiling.

 That's the sort of **"high probability of improvement"** map you want.

---

 # 6\. For the actual recommendation score, I'd optimize expected pp gain

 This is the most important part.

 Don't make your final score:

```
similarity(player, map)
```

 Instead:

 $$
Score(map)
=
P(\text{good score} \mid player,map)
\times
PP_{\text{potential}}
$$

 Where "good score" might mean:

 > probability of achieving ≥ X% of the map's maximum attainable pp.

 For example:

```
Map A:
potential pp = 400
probability player gets 85%+ = 0.55

score = 220
```

 versus:

```
Map B:
potential pp = 500
probability player gets 85%+ = 0.20

score = 100
```

 So Map A is the better recommendation.

 This naturally produces the behavior you're looking for:

 > **maps that are difficult enough to produce a meaningful pp gain but realistic enough that the player can actually perform on them.**

---

 # 7\. I'd explicitly model the player's "pp frontier"

 This could become the centerpiece of the system.

 For every skill/category, estimate:

```
difficulty → expected pp / performance
```

 Then find the point where performance begins falling off.

 For example:

```
Aim

6.0★ ───────── 300pp expected
6.3★ ───────── 330pp
6.6★ ───────── 350pp
6.9★ ───────── 340pp
7.2★ ───────── 280pp
```

 The interesting recommendation region is around:

```
6.5–6.9★
```

 because that's where the player is approaching their current limit.

 You can do this independently for your classifier's dimensions.

 Then recommendation becomes:

 > Find maps close to the player's frontier, but slightly beyond their demonstrated ability.

 That's substantially better than recommending maps similar to their top plays.

---

 # 8\. What about mods?

 I **would not just feed the raw modded stats into the classifier without thinking about representation**.

 The mod is part of the task.

 For example, a player doing:

```
7★ NM
```

 and

```
6.5★ DT
```

 is demonstrating different abilities.

 DT changes the temporal difficulty of the map, while HR changes things like CS/OD/AR; mods therefore materially alter the difficulty characteristics used by pp.  osu!+1

 ### Best approach

 Run your map classifier on the **actual modded beatmap representation**.

 Conceptually:

```
original map
      ↓
apply mods
      ↓
extract features
      ↓
classifier
      ↓
{aim: .72, speed: .61, tech: .20}
```

 rather than:

```
original map
      ↓
classifier
      ↓
{aim: .72, speed: .40, tech: .20}

+ DT multiplier
```

 because the mod can fundamentally change what makes the map difficult.

 This is especially important for things like DT/HT and HR.

---

 # 9\. But preserve the mod as a separate feature too

 I'd actually represent a play as:

```
map_features
mod_features
result_features
```

 For example:

```
{
  "map": {
    "aim": 0.71,
    "speed": 0.54,
    "tech": 0.23
  },

  "mods": {
    "HD": true,
    "HR": false,
    "DT": true
  },

  "difficulty": {
    "stars": 6.8,
    "ar": 10.3,
    "od": 9.5,
    "cs": 4.0,
    "bpm": 280
  },

  "performance": {
    "accuracy": 0.965,
    "combo_ratio": 0.91,
    "misses": 3,
    "pp": 285
  }
}
```

 The classifier sees the **effective map**, while your recommender sees the **mod context**.

---

 # 10\. Don't let mods create fake skill

 This is a subtle problem you'll encounter.

 Suppose somebody's top plays are all DT.

 Your system could conclude:

 > "This person is extremely good at speed."

 But maybe they're specifically good at **DT aim** rather than raw speed.

 So I'd eventually want your categories to become more granular than:

```
aim
speed
tech
```

 Something closer to latent dimensions such as:

```
jump aim
flow aim
stream speed
burst speed
finger control
reading
rhythm complexity
technical aim
high AR
low AR
```

 You don't necessarily need to manually define all of those.

 Your classifier could produce an embedding instead:

```
map → 32/64/128 dimensional difficulty embedding
```

 and your human-readable categories can be projections of that embedding.

 That will probably produce a much better recommender.

---

 # 11\. A very practical first version

 If I were implementing v1, I'd do this:

 ### Step 1 — Represent every play

```
map embedding/category vector
effective star rating
mods
accuracy
combo %
miss count
pp
timestamp
```

 ### Step 2 — Calculate a performance score

 Something like:

```
performance =
    f(
        accuracy,
        combo_ratio,
        miss_rate,
        normalized_pp,
        difficulty
    )
```

 Don't make pp the sole input.

 ### Step 3 — Create two profiles

```
long_term_profile = weighted(top_plays)

recent_profile = weighted(recent_plays)
```

 ### Step 4 — Estimate the player's frontier

 For each region of the map embedding:

```
difficulty → probability of strong performance
```

 Use a regression model, gradient-boosted trees, or even a simple logistic model initially.

 ### Step 5 — Generate candidates

 Filter out maps that are:

 - substantially below the player's current ability
- absurdly above it
- already played recently
- duplicates / near-duplicates
- maps where the player already has an excellent score

 ### Step 6 — Rank by expected gain

 Something like:

 $$
R(m) =
P(\text{strong score on }m)
\times
PP_{\text{achievable}}(m)
\times
Novelty(m)
\times
CurrentInterest(m)
$$

 I'd probably make `Novelty` fairly small; otherwise you'll recommend weird maps simply because they're different.

---

 # 12\. And there's a really nice way to train this

 Once you have historical data, you don't have to hand-design the perfect formula.

 For each player, take a historical point in time:

```
plays before T
       ↓
player profile
       ↓
recommendation algorithm
       ↓
maps played after T
```

 Then ask:

 > Could the system have predicted which maps this player would set unusually good scores on?

 This gives you an offline evaluation dataset.

 Your target could be:

```
future pp / expected pp
```

 or:

```
future score percentile
```

 or even:

```
did player improve their previous best pp on this map?
```

 I'd favor something like **future performance relative to predicted performance**, because otherwise your model learns to recommend easy maps.

---

 ## One thing I'd change about the objective

 I wouldn't optimize:

 > **"maps the player could do well on."**

 I'd optimize:

 > **"maps where the player has a high probability of setting a score substantially better than their existing score, with meaningful pp value."**

 Those are different.

 A map where they have an 80% chance of getting 300pp isn't necessarily useful if they already have 290pp on it.

 But a map where they have a 35% chance of getting **450pp**, and a 65% chance of getting 300pp, may be an excellent recommendation.

 So the ultimate quantity I'd like the recommender to estimate is:

 $$
\boxed{
E[\text{new best pp} - \text{existing best pp}]
}
$$

 possibly multiplied by the probability of actually achieving it.

 That gets you very close to the product goal you're describing: **recommend the maps that are most likely to produce the player's next meaningful pp breakthrough.**  osu!

 If you tell me what features your current classifier outputs (e.g. just `aim/speed/tech`, or probabilities + star rating), I can sketch a concrete scoring algorithm/data schema for this, including exactly how I'd weight **top vs recent plays, accuracy vs pp, mods, and difficulty**.

  Sources