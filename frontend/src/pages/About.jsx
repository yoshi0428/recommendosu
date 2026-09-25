import {Button, Container} from 'react-bootstrap'
import {Link} from 'react-router-dom'

import useTheme from '../hooks/useTheme'


function About() {
  const {theme} = useTheme()

  const sectionClass = theme === 'dark'
    ? 'bg-secondary bg-opacity-10 border-secondary'
    : 'bg-white border-light-subtle'

  return (
    <div
      className={
        theme === 'dark'
          ? 'bg-dark text-light min-vh-100'
          : 'bg-light text-dark min-vh-100'
      }
    >
      <Container className="py-5">

        <div className="mb-4">
          <Button
            as={Link}
            to="/"
            variant="outline-secondary"
          >
            Back to Recommendations
          </Button>
        </div>

        {/* INTRO */}
        <div className={`p-4 mb-4 rounded border ${sectionClass}`}>
          <h3 className="mb-3">
            About
          </h3>

          <p>
            An osu! beatmap recommender that I wrote to apply all my knowledge from my Computer Science bachelors. It
            initially started because someone in my MapleStory guild talked about one of his friends using a recommender
            to find beatmaps (if you see this Ken, what's up 👀). I was looking for a bigger scale project to complete by
            myself that somewhat involved ML/DL.
          </p>

          <p className="mb-3">
            This{' '}
            <a
              href="https://github.com/yoshi0428/recommendosu"
              target="_blank"
              rel="noopener noreferrer"
            >
              project
            </a>{' '}
            uses Python with FastAPI for the backend, SQLite for
            the database, and react-bootstrap for the frontend. It is currently
            deployed on this website using my PC and Docker Compose.
          </p>

          <p className="mb-3">
            If you need to contact me, do it via{' '}
            <a
              href="https://osu.ppy.sh/users/10961031"
              target="_blank"
              rel="noopener noreferrer"
            >
              yoshi0428
            </a>{' '}
            at osu!pm or <u>yoshiekn</u> on Discord.
          </p>

          <p className="mb-0">
            I've also made a Discord server{' '}
            <a
              href="https://discord.gg/Dh4TzKGGB7"
              target="_blank"
              rel="noopener noreferrer"
            >
              here
            </a>
            , if you want to see the changelogs.
          </p>
        </div>

        {/* MODS */}
        <div className={`p-4 mb-4 rounded border ${sectionClass}`}>
          <h3 className="mb-3">
            Mods
          </h3>

          <p>
            You can exclude mods by clicking the checkbox twice for a minus
            sign. The unchecked mods will be part of mod combinations that may
            get recommended.
          </p>

          <p>
            You can also check multiple mods for the same combinatorial effect.
          </p>

          <p>
            Checking a single mod will result in only being recommended that
            single mod.
          </p>

          <p className="mb-0">
            If you need an exact mod combination, turn on the "Exact
            combination" toggle in Advanced.
          </p>
        </div>

        {/* RECOMMENDATION GOALS */}
        <div className={`p-4 mb-4 rounded border ${sectionClass}`}>
          <h3 className="mb-3">
            Recommendation Goals
          </h3>

          <p>
            recommendosu offers several recommendation profiles that adjust how
            candidate beatmaps are ranked. Each profile combines content
            similarity, difficulty, mod preference, and optional signals such as
            PP potential or tournament category classification.
          </p>

          <hr className="my-4"/>

          <h4 className="mt-4 mb-3">
            Balanced
          </h4>

          <p>
            The <strong>Balanced</strong> profile is the default recommendation
            mode. It primarily prioritizes maps that are similar to your
            existing plays, while also considering how closely their difficulty
            matches your preferences. Mod preferences have a small influence on
            the final ranking.
          </p>

          <p>
            <strong>Weights:</strong> 65% content similarity --- 30% difficulty
            --- 5% mod preference
          </p>

          <hr className="my-4"/>

          <h4 className="mt-4 mb-3">
            PP Potential
          </h4>

          <p>
            The <strong>PP Potential</strong> profile places additional emphasis
            on maps that may offer higher performance-point potential. Content
            similarity remains the largest factor, while difficulty and
            estimated PP potential each have a substantial influence on the
            ranking. See the "PP Potential Explained" section below.
          </p>

          <p>
            <strong>Weights:</strong> 45% content similarity --- 25% difficulty
            --- 25% PP potential --- 5% mod preference
          </p>

          <hr className="my-4"/>

          <h4 className="mt-4 mb-3">
            NM1–5
          </h4>

          <p>
            The <strong>NM1–5 Classifier</strong> profile incorporates a player's
            preferences across the five No Mod tournament categories (NM1–NM5).
            These player preferences are derived from their past plays, taking
            into account factors such as recency, top-play performance, and PP
            performance.
          </p>

          <p>
            For each candidate, the recommendation system compares the player's category preferences against the
            precomputed CNN-XGBoost classification probabilities of the beatmap's NM variant. The resulting similarity
            is used as an additional component of the recommendation score.
          </p>

          <p>
            Since the classification is based on the base beatmap rather than
            a specific modded variant, this signal can still influence
            recommendations when the final recommended variant uses mods.
          </p>

          <p>
            <strong>Weights:</strong> 50% content similarity --- 25% difficulty
            --- 20% NM1–5 category match --- 5% mod preference
          </p>

          <hr className="my-4"/>

          {/* QUICK NOTICE */}
          <h5 className="mb-0">
            The following sections will go into more depth on difficulty, PP potential, and mod preference scores. I
            find content similarity pretty intuitive, but just know that it
            uses{' '}
            <a
              href="https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.KDTree.html"
              target="_blank"
              rel="noopener noreferrer"
            >SciPy's KDTree
            </a>{' '}
            to find each top & recent play's top 20000 nearest neighbors.
          </h5>
        </div>


        {/* DIFFICULTY PROFILE */}
        <div className={`p-4 mb-4 rounded border ${sectionClass}`}>
          <h3 className="mb-3">
            Difficulty Profile
          </h3>

          <p>
            The difficulty score measures how closely a recommended map matches the difficulty characteristics of your
            played maps. It considers{' '} <strong>Star Rating (SR), Approach Rate (AR), Overall Difficulty (OD), and
            BPM</strong>. The difficulty score is then combined with content similarity and other recommendation signals
            according to the selected recommendation goal.
          </p>

          <hr className="my-4"/>

          <h4 className="mt-4 mb-3">
            Difficulty Feature Weights
          </h4>

          <p>
            Each characteristic is standardized relative to your demonstrated difficulty profile, then combined into a
            weighted distance. Maps closer to your profile receive a higher difficulty score, while maps farther away
            receive a lower score.
          </p>

          <p><strong>Weights:</strong>{' '} SR 4.0 --- AR 1.5 --- OD 1.0 --- BPM 0.5 </p>

          <hr className="my-4"/>

          <h4 className="mt-4 mb-3">
            Difficulty Standard Deviation Floors
          </h4>

          <p>
            To prevent unusually small variations from having an outsized effect on the score, each feature also has a
            minimum standard-deviation threshold.
          </p>

          <p><strong>Threshold values:</strong>{' '} SR 0.35 --- AR 0.50 --- OD 0.50 --- BPM 15 </p>

          <p>
            The recommender also applies a <strong>minimum difficulty threshold</strong> based on your demonstrated Star
            Rating. This prevents content similarity from causing recommendations to fall substantially below your
            demonstrated difficulty level. There used to be an issue where mrekk was recommended 6-7* NM maps and 10-11*
            HDHRDT combination maps.
          </p>

          <p className={"mb-0"}>
            If you absolutely need to nullify this minimum difficulty threshold, set the
            difficulty profile's standard deviations floors to very large numbers.
          </p>

        </div>

        {/* MOD PREFERENCE */}
        <div className={`p-4 mb-4 rounded border ${sectionClass}`}>
          <h3 className="mb-3">
            Mod Preferences
          </h3>

          <p>
            Your mod preferences are inferred from the mod
            combinations in your recorded plays. Each play contributes a weighted amount based on whether it is a top
            play
            or a recent play, with higher-PP plays receiving a small additional contribution.
          </p>

          <p><strong>Source weights:</strong>{' '} Top plays 3.0x --- Recent plays 1.0x</p>

          <hr className="my-4"/>

          <p>
            Top plays receive more weight because they may provide stronger evidence of the mod combinations you tend to
            choose for your strongest performances. Plays that appear in both the top and recent collections are counted
            only once as top plays.
          </p>

          <p>
            PP also provides a small additional weighting factor. Higher-PP plays receive slightly more influence, with
            diminishing returns so that extremely high-PP scores do not dominate the preference profile.
          </p>

          <p><strong>Score weight:</strong>{' '} [TOP_WEIGHT or RECENT_WEIGHT] * (1 + PP_WEIGHT * sqrt(PP) / 10)</p>

          <hr className="my-4"/>

          <p className="mb-0">
            After the weighted preferences are calculated, they are log-transformed and normalized so that your most
            preferred mod combination has a preference value of 1.0. These normalized preferences are then used as one
            of the signals when ranking recommendations.
          </p>
        </div>

        {/* ABILITY PROFILE */}
        <div className={`p-4 mb-4 rounded border ${sectionClass}`}>
          <h3 className="mb-3">
            Ability Profile
          </h3>

          <p>
            Your difficulty profile is built from your recorded plays, with each play contributing a different amount of
            weight when estimating your demonstrated difficulty. Recent plays are given more importance because they are
            possibly a better indicator of your current ability.
          </p>

          <p>
            A play's weight is determined by three factors: <strong>recency, score source, and PP</strong>. The recency
            component uses a 30-day half-life, meaning a play contributes half as much after 30 days, one quarter as
            much after 60 days, and so on.
          </p>

          <p>
            <strong>Source weights:</strong>{' '}
            Top plays 1.0x --- Recent plays 2.0x
          </p>

          <hr className="my-4"/>

          <p>
            Plays that appear in both collections are treated as recent plays rather than being counted twice. Higher-PP
            plays also receive slightly more weight when estimating ability. This provides a small additional emphasis
            on stronger performances without allowing PP to dominate the profile.
          </p>

          <p className="mb-0">
            <strong>PP influence:</strong>{' '}
            1 + ABILITY_PP_WEIGHT * sqrt(PP) / 10
          </p>
        </div>

        {/* PP POTENTIAL EXPLAINED */}
        <div className={`p-4 mb-4 rounded border ${sectionClass}`}>
          <h3 className="mb-3">
            PP Potential Explained
          </h3>

          <p>
            The <strong>PP Potential</strong> signal estimates how
            promising a candidate is for earning PP relative to your demonstrated difficulty. It is not an estimate of
            how
            much PP you are guaranteed to gain.
          </p>

          <p>
            Candidates receive more PP-potential value when they offer higher
            PP while remaining within a reasonable range of your demonstrated difficulty. Maps below your usual
            difficulty
            receive a reduced score, while maps that are substantially beyond your demonstrated difficulty are
            penalized.
          </p>

          <p>
            The system uses <strong>0.75 standard deviations</strong> above your demonstrated
            difficulty as the point at which the below-ability penalty stops. Candidates closer than 0.75 standard
            deviations to your profile receive a reduced PP-potential score. Candidates between <strong>0.75 and 2.0
            standard deviations</strong> above or below this range do not receive an additional difficulty penalty.
          </p>

          <p>
            Candidates more than <strong>2.0 standard deviations</strong> from your demonstrated difficulty receive an
            increasingly strong penalty. This prevents extremely difficult maps from receiving a high PP-potential score
            solely because their raw PP is high.
          </p>

          <p>
            Candidate PP is transformed using a logarithmic scale, so
            higher PP values increase the score with diminishing returns. This prevents extremely high-PP maps from
            completely dominating the recommendation.

          </p>

          <p className="mb-0">
            <strong>PP potential parameters</strong>{' '}
            <p className="mt-0 mb-0">Below-ability threshold (PP Push Target Z) --- 0.75 standard deviations</p>
            <p className="mt-0 mb-0">Maximum difficulty range (PP Push Maximum Z) --- 2.0 standard deviations</p>
          </p>
        </div>

        <div className="mb-4">
          <img
            src="GoT80k9H6Gd1x.gif"
            alt="quagsire"
            className="img-fluid d-block mx-auto"
            style={{maxWidth: '400px'}}
          />
        </div>

      </Container>
    </div>
  )
}


export default About