Yeah — **“players around my rank → maps they play” is only one family of candidate generation**, and it’s arguably not the most interesting one.

 For osu!, I’d think of the recommender as a **two-stage system**:

 1. **Candidate generation:** cheaply get, say, 1k–100k plausible maps.
2. **Ranking:** use a much more expensive personalized model to select the best 20–100.

 There are several very different ways to do stage 1.

 ## 1\. Similar-player collaborative filtering

 This is basically what you're describing:

 > Find players whose performance/play history resembles mine → collect maps they play → remove maps I've played.

 There are multiple notions of "similar":

 - rank / pp
- per-mod performance
- accuracy distribution
- skill profile
- map-type preferences
- actual map-play overlap

 The last one is much more powerful than rank proximity.

 For example, if you and another player have both played 300 of the same maps, you can represent each player as a sparse vector of map interactions and use cosine/Jaccard/ALS/etc. to find similar users.

 Then:

 $$
C_u = \bigcup_{v\in NN(u)} \text{maps}(v)
$$

 weighted by similarity.

 This is essentially the philosophy behind **Pupsbot**, which explicitly looks at similar players and their performances to generate maps.  GitHub

 An older osu! project, **OsuHelper**, did something particularly interesting: it searched for players who performed similarly on maps you had played and used _their_ top plays as recommendations.  GitHub

---

 ## 2\. Item-to-item collaborative filtering

 Instead of asking:

 > "Which players are like me?"

 ask:

 > "Which maps tend to be played by the same people as the maps I like?"

 This is surprisingly attractive for osu!.

 Imagine you played:

 - Freedom Dive
- Image Material
- some tech map
- some DT stream map

 You can construct co-occurrence:

 $$
M_{ij} = \#\{\text{players who played both }i,j\}
$$

 Then candidate maps are neighbors of your played maps:

 $$
score(i) = \sum_{j\in H_u} w_j \, sim(i,j)
$$

 This has a major advantage: **you don't need to model what "similar skill" means explicitly.**

 There's actually an osu! project called **osu!Oracle** that does essentially this at a more sophisticated level using an Item2Vec-style embedding. Beatmap-mod combinations are embedded according to how frequently they're observed together, and cosine similarity gives recommendations.  osu!

 This is probably one of the first things I'd prototype.

---

 ## 3\. Map/content embeddings

 Here you ignore other players entirely.

 Represent every beatmap as a vector:

 $$
z_i = f(\text{beatmap structure})
$$

 Features could include:

 - SR / AR / CS / OD
- BPM
- length
- object density
- jump distance distributions
- rhythm distributions
- velocity changes
- angle distributions
- stream/burst characteristics
- slider characteristics
- aim/speed/tech features
- mod-adjusted characteristics
- even raw note sequences processed by a Transformer/CNN

 Then take embeddings of maps the player performs well on and find nearby maps:

 $$
score(i) = \max_{j\in H_u} \cos(z_i,z_j)
$$

 or some weighted aggregation.

 This gives you **content-based recommendation** and solves cold-start for new maps much better than collaborative filtering.

 A recent osu! recommender project combines a learned beatmap embedding with implicit ALS: the map representation is learned from beatmap structure, while user preference is learned from replay interactions.  Bryan Chan

 That's a pretty compelling architecture.

---

 ## 4\. Performance prediction

 This is a different paradigm altogether:

 > Don't predict what map the player likes. Predict how well the player would perform on every map.

 For candidate map $i$:

 $$
\hat{acc}_{u,i}=f_u(\text{map}_i)
$$

 or

 $$
\hat{pp}_{u,i}=f_u(\text{map}_i,\text{mods})
$$

 Then recommend maps satisfying something like:

 $$
\text{expected pp}_{u,i} > \text{current weighted pp}
$$

 This is what **Combine** did years ago: it trained a neural network on a player's replays to predict their accuracy on a beatmap, then used predicted performance/PP to decide whether a map was worth recommending.  GitHub+1

 This is really interesting because **candidate generation itself can be based on predicted performance**.

 You could retrieve maps around a desired predicted accuracy:

 > "Give me maps where this player is predicted to get 96–98%."

 rather than:

 > "Give me maps played by people like this player."

---

 ## 5\. Skill-profile matching

 This is a middle ground.

 Instead of embedding maps from their raw geometry, give maps a vector of estimated skills:

 $$
m_i =
[
\text{aim},
\text{speed},
\text{acc},
\text{tech},
\text{stamina},
\text{reading},
\text{flow},
\dots
]
$$

 and estimate the player's profile:

 $$
p_u =
[
0.8,0.4,0.7,0.9,\dots
]
$$

 Then retrieve maps close to $p_u$.

 The interesting bit is that **the player's profile should ideally be inferred from performance**, rather than from rank.

 For example, two 5k players could have radically different profiles:

```
player A: aim .9 / speed .3 / tech .7
player B: aim .4 / speed .9 / tech .5
```

 A rank-based candidate generator would conflate them.

 A skill-space generator wouldn't.

---

 ## 6\. "Maps adjacent to your plays"

 This is a simpler variant of #3 that can work extremely well.

 Take the player's best/recent plays and find maps that are:

 - ±0.3 SR
- similar AR
- similar BPM
- similar length
- similar object density
- similar aim/speed decomposition
- similar rhythm characteristics

 But importantly, **don't necessarily retrieve the nearest maps globally**.

 For each played map:

 $$
C_j = NN(z_j)
$$

 then union the neighborhoods.

 This creates a nice property:

 > "You played _this_ map well, so here's a slightly different map occupying the same region."

 You can also deliberately search **slightly outside** the player's current manifold to produce improvement-oriented recommendations.

---

 ## 7\. Sequence/session-based recommendation

 This is underexplored in osu!, IMO.

 Treat a player's plays as a sequence:

```
map A → map B → map C → map D
```

 and learn:

 $$
P(map_{t+1}\mid map_1,\ldots,map_t)
$$

 This is basically the same idea behind session-based recommenders.

 You might discover that:

 > Players who just played high-BPM stream map X often go on to play Y/Z.

 That's different from long-term preference.

 For osu! this could be especially useful because players have **session intent**:

```
"I'm warming up"
"I'm farming"
"I'm practicing streams"
"I'm playing tech"
"I'm tilted and playing easy shit"
```

 Recent plays can reveal that intent much better than their overall profile.

---

 ## 8\. Popularity/trending candidates

 Boring, but useful as a component.

 Candidates can simply come from:

 - recently ranked maps
- maps gaining plays
- maps popular among the player's rank bracket
- maps popular among similar players
- maps with high-quality scores recently submitted

 This provides **exploration**.

 Otherwise a collaborative filter tends to become:

 > "You played these 20 farm maps, here are 200 more maps that everyone who plays those maps also plays."

 You get a nasty feedback loop.

---

 ## 9\. Graph-based retrieval

 You can combine a lot of the above into one graph.

 Nodes:

```
players
maps
mapsets
mods
skills
artists
genres
tags
```

 Edges:

```
player --played--> map
player --performed--> map
map --same-set--> map
map --similar--> map
player --similar--> player
map --has-tag--> tag
map --uses-mod--> mod
```

 Then recommendation becomes graph traversal.

 For example:

```
              similar player
                    ↓
your plays → map A → map B
     ↓              ↓
  map C --------→ map D
```

 You can use personalized PageRank, random walks, graph embeddings, LightGCN, PinSage-style retrieval, etc.

 This is probably the most generalizable architecture if you have a large interaction dataset.

---

 # What I'd actually build

 If I were making an osu! recommender from scratch, I'd **not choose one candidate generator**.

 I'd make several generators and union them:

```
                   ┌─ similar players ───────┐
                   │                         │
                   ├─ item-item CF ──────────┤
player history ────┼─ map embeddings ────────┼──→ 10k candidates
                   ├─ skill-space retrieval ─┤
                   ├─ performance prediction ┤
                   └─ exploration/popularity ─┘
                                             │
                                             ↓
                                      filtering
                                             │
                                             ↓
                                    ranking model
                                             │
                                             ↓
                                       top 50
```

 And **I'd deliberately make the generators disagree**.

 For example, for a user:

```
2,000 candidates from similar players
2,000 from item-CF
2,000 from map embedding
2,000 from predicted-performance retrieval
1,000 from exploration
1,000 from recent/trending
```

 Deduplicate → maybe 5–8k candidates.

 Then your expensive ranker can use all the information:

 $$
R(u,i) =
f(
  \text{user embedding},
  \text{map embedding},
  \text{predicted acc},
  \text{predicted pp},
  \text{similar-player score},
  \text{item-CF score},
  \text{novelty},
  \text{recency},
  \text{map quality},
  \text{recent session context}
)
$$

 That architecture is much more powerful than trying to make **one magical nearest-neighbor metric**.

 And there's an especially nice trick here: **candidate-generator provenance becomes a feature**. If a map was independently retrieved by 4 different generators, that's a very strong signal:

```
map X
  similar-player      ✓
  item-CF             ✓
  content embedding   ✓
  performance model   ✓
  popularity          ✗
```

 I'd expect that to be an excellent candidate before even doing sophisticated ranking.

 One other interesting direction is **negative feedback**. In osu! you don't really have explicit dislikes, but things like _played once and never touched again_, _repeated retries without improvement_, or _consistently low accuracy despite similar maps_ can provide useful implicit negatives. The recent PP Recommender work explicitly uses implicit interactions such as play/replay/mastery signals rather than explicit ratings.  Bryan Chan

 So your original nearest-neighbor idea is definitely viable — but I'd think of it as **one retrieval channel in a multi-retriever system**, rather than _the_ recommender.