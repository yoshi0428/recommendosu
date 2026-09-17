# NM Significance

- NM1 -> Aim
- NM2 -> Stream, Tapping, and Stamina
- NM3 -> Flow and Snap Alt
- NM4 -> Mech tech and slider tech
- NM5 -> Finger control, speed, and strain tapping

# CNN

It's essentially saying:

- "Based on the pattern/geometry/timing of this map, this looks overwhelmingly like an NM4-style map."

That's useful, but it's also a fairly narrow view of the problem.

The CNN has learned patterns such as:

- object spacing 
- movement patterns
- timing
- jumps/streams
- slider characteristics
- density
- etc.

It doesn't necessarily know how all of those characteristics interact with your other metadata.

# XGBoost

Your XGBoost meta-model receives the CNN's output plus your additional features.

So instead of asking:

- "What tournament category does this map look like?"

it's closer to asking:

- "Given what the CNN thinks this map is, its difficulty characteristics, mod-adjusted stats, and other metadata, what category makes the most sense?"

That's a much more powerful question.