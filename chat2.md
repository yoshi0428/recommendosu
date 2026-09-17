That actually makes the problem much simpler. If you can query **all category confidence scores** for a map, I'd use the classifier as a _difficulty composition_ signal, not as the recommender itself.

 The important thing is to distinguish **"what skill is this map?"** from **"how good is this player at that skill at this difficulty?"**

 ## 1\. Turn each map into a category vector

 Even if the classifier normally returns:

```
aim: 0.87
```

 I'd expose the full distribution:

```
aim:   0.87
speed: 0.08
tech:  0.04
...
```

 Ideally these are normalized probabilities:

 $$
\mathbf c_m = [P(aim),P(speed),P(tech),...]
$$

 So a hybrid map naturally looks like:

```
aim   0.52
speed 0.39
tech  0.07
```

 This is considerably more useful than assigning it a single label.

---

 ## 2\. Build a profile of the player by category _and difficulty_

 This is where I'd spend most of the effort.

 Suppose a player has these plays:

 | Map | Category | SR | Acc | pp |
| --- | --- | --- | --- | --- |
| A | aim | 6.0 | 98.5% | 300 |
| B | aim | 6.5 | 97.2% | 320 |
| C | speed | 5.8 | 94.0% | 250 |
| D | speed | 6.2 | 88.5% | 220 |
| E | tech | 6.0 | 97.0% | 290 |

You can infer:

```
Aim:
  strong around 6.0–6.5

Speed:
  substantially weaker

Tech:
  strong
```

 But don't just calculate a single "aim skill = 0.8."

 You want a function:

 $$
S_p(c,d)
$$

 meaning:

 > How well does player $p$ perform on category $c$ at difficulty $d$?

 Then you can evaluate a candidate map against that function.

---

 # 3\. Weighting plays: I'd use pp, but normalized

 I agree with your concern about raw pp.

 Consider:

```
Top play:     400 pp
Recent play:  150 pp
```

 It would be silly for the top play to have \~3× the influence merely because its raw pp is higher.

 Instead, I'd separate **play strength** from **importance**.

 For example:

 $$
w_i =
w_{\text{performance}}
\times
w_{\text{recency}}
\times
w_{\text{difficulty}}
$$

 ### Performance

 Use pp **relative to the difficulty**, rather than raw pp.

 You could start with something crude like:

 $$
p_i = \frac{pp_i}{SR_i^\alpha}
$$

 and tune $\alpha$.

 Even better, eventually learn an expected-pp curve and use:

 $$
p_i = \frac{pp_i}{E[pp\mid SR_i]}
$$

 So a play gets high weight when it is unusually good for its difficulty.

 ### Recency

 Use exponential decay:

 $$
w_{\text{recency}} = e^{-\lambda \Delta t}
$$

 But I wouldn't make recency too aggressive.

 Recent plays are valuable because they tell you what the player is **currently practicing**, not necessarily because they're better evidence of ability.

---

 # 4\. Distribute a play's weight across categories

 This is where your confidence output becomes very useful.

 Suppose:

```
Map 1:
aim   .90
speed .07
tech  .03
```

 and the player gets a great score.

 Give almost all of that evidence to aim.

 For a hybrid:

```
Map 2:
aim   .55
speed .40
tech  .05
```

 the play contributes to both aim and speed.

 So:

 $$
Evidence_{p,c}
=
\sum_i w_i P(c\mid map_i)
$$

 But again, I'd keep difficulty attached:

 $$
Evidence_{p,c,d}
=
\sum_i w_i P(c\mid map_i)K(d,d_i)
$$

 where $K$ is a kernel that says how relevant a play at difficulty $d_i$ is to difficulty $d$.

 A Gaussian kernel would be a perfectly reasonable first implementation:

 $$
K(d,d_i)=e^{-\frac{(d-d_i)^2}{2\sigma^2}}
$$

 Now you effectively have a smooth skill surface.

---

 # 5\. This gives you a very nice recommendation mechanism

 For candidate map $m$:

```
classifier:
aim   .60
speed .30
tech  .10

SR = 6.7
```

 Calculate:

 $$
P_{success}(m)
=
0.60S_p(aim,6.7)
+
0.30S_p(speed,6.7)
+
0.10S_p(tech,6.7)
$$

 That's already a reasonable first model.

 But there's an even better formulation.

---

 # 6\. Look for the "edge" of the player's ability

 You don't want:

 > maps that match the player's strongest skills.

 You want:

 > maps that match the player's strongest skills **at a difficulty where they're near their limit**.

 For example:

```
                 Player performance

Aim       6.0★ ██████████
          6.5★ █████████
          7.0★ ███████
          7.5★ ███

Speed     6.0★ ███████
          6.5★ ████
          7.0★ ██
```

 A 5.5★ aim map is probably useless for pp farming.

 A 9★ aim map is probably unrealistic.

 The interesting region is around:

```
6.8–7.2★ aim
```

 So I'd explicitly model a **difficulty frontier** for each category.

---

 # 7\. Then rank by expected pp improvement

 This is the part I'd ultimately optimize.

 For a candidate map, estimate:

 $$
P(\text{new high pp})
$$

 and:

 $$
PP_{\text{new best}}
$$

 Then:

 $$
RecommendationScore
=
P(\text{new best})
\times
(PP_{\text{new best}}-PP_{\text{current}})
$$

 For example:

 ### Map A

```
Expected pp:       350
Current best:      250
Chance of achieving: 70%

score = .70 × 100 = 70
```

 ### Map B

```
Expected pp:       500
Current best:      250
Chance of achieving: 20%

score = .20 × 250 = 50
```

 Map A wins.

 This is much closer to your actual objective than similarity.

---

 # 8\. I'd add a "stretch" parameter

 You probably don't want the mathematically optimal answer to always be the easiest high-confidence pp farm.

 Let:

 $$
q = P(\text{successful performance})
$$

 Then rank something like:

 $$
Score = PP_{gain}\times q^\beta
$$

 where $\beta$ controls how conservative you are.

 But I'd actually make this a **tunable recommendation mode**:

```
Safe:
  prioritize high probability

Balanced:
  probability × pp gain

Stretch:
  accept lower probability for much higher pp ceiling
```

 That could be a really nice product feature.

---

 # 9\. Mods: I'd definitely query the classifier on the modded map

 Given your setup, I'd do:

```
base beatmap
    +
mods
    ↓
effective beatmap
    ↓
classifier
    ↓
full category distribution
```

 So for the same map:

```
NM:
aim .72
speed .18
tech .10
```

 might become:

```
DT:
aim .43
speed .51
tech .06
```

 That's exactly the information your recommender wants.

 I would **not** try to manually adjust the classifier's output based on the mod.

 However, keep the mod as a separate feature because the player's demonstrated ability with:

```
NM
HD
HR
DT
HDDT
```

 can differ substantially.

 So your player profile should ideally be:

 $$
S(p, category, difficulty, mod)
$$

 rather than merely:

 $$
S(p, category, difficulty)
$$

 You don't necessarily need enough data to model every mod independently. You can initially group them:

```
NM
HR
DT
HT
EZ
HD
```

 and only add interactions when you have enough observations.

---

 # 10\. One thing I'd be careful about with your classifier

 If it outputs:

```
aim .51
speed .49
```

 that doesn't necessarily mean the map is genuinely a 50/50 hybrid.

 It could mean:

 > "The classifier is uncertain."

 Those are very different things.

 If you can inspect the confidence/distribution, I'd distinguish:

```
True hybrid:
aim   .50
speed .48
tech  .02
```

 from:

```
Uncertain:
aim   .34
speed .33
tech  .33
```

 The first is strong evidence of aim+speed.

 The second should probably have **less influence** on the player profile because the classifier doesn't know what the map is.

 You could therefore use classifier certainty as another weight:

 $$
w_i \leftarrow w_i \times C(map_i)
$$

 where $C$ measures how concentrated the category distribution is.

---

 # 11\. What I'd build first

 You can get surprisingly far without ML on the recommender itself.

 I'd implement:

```
                         ┌── top plays ───────┐
                         │                    │
                         ├── recent plays ────┤
                         │                    ▼
                         │             weighted play history
                         │                    │
                         │                    ▼
                         │          category × difficulty
                         │             skill profile
                         │                    │
                         │                    ▼
candidate maps ──► classifier ──► category distribution
                         │                    │
                         └────────────────────┤
                                              ▼
                                   predicted performance
                                              │
                                              ▼
                                      expected pp gain
                                              │
                                              ▼
                                         ranking
```

 And specifically, I'd start with:

 1. **Full category probability vector** from your classifier.
2. **Separate long-term and recent profiles.**
3. **Difficulty-aware weighting** rather than just category averages.
4. **Normalized performance/pp**, rather than raw pp.
5. **Effective modded map → classifier**.
6. Rank candidates by **expected pp improvement**, not category similarity.
7. Later, train a model to replace the hand-designed `predicted performance` function.

 The last step is where I think this could become genuinely powerful. Once you have enough historical play data, you can train:

 $$
f(player\ history,\ map\ vector,\ difficulty,\ mods)
\rightarrow
P(\text{player achieves }X\text{ pp})
$$

 and directly optimize it against **future pp gains**. Your classifier then becomes one of the inputs to that model rather than the thing making the recommendation itself.

 That also gives you a clean offline test: take a player's history at time **T**, generate recommendations using only information available at T, and measure how much better their actual subsequent plays were on those recommendations.