import LegalPage, { Contact, External, Section } from "../components/LegalPage";

// What the site stores: [what, when, how long].
const STORED_DATA = [
  [
    "Your login session: a random session ID and your osu! player ID",
    "You log in",
    "Until you log out. A session stops working after 30 days. The expired entry stays on the server until that session is used again or the operator deletes it",
  ],
  [
    "The osu! access token and refresh token (keys that osu! gives the site for your account)",
    "You log in",
    "Deleted together with your login session",
  ],
  [
    "The public top and recent scores of a player",
    "You run the recommender for that player, or the site looks for plays after a click (see \"Clicks and previews\")",
    "Kept, and refreshed later",
  ],
  [
    "Your public play history: each map that you played, with its play count",
    "You run the recommender for your own account",
    "Kept, and updated at most once a day while you use the site",
  ],
  [
    "Clicks and previews (see below)",
    "You click a recommendation or play its audio preview",
    "Kept",
  ],
  [
    "Your latest list of recommendations",
    "You run the recommender",
    "In memory, for 30 minutes after your last use or until your next run",
  ],
  [
    "Server logs. They can include your IP address, your browser type, the pages that you request, and osu! player IDs",
    "You use the site",
    "Until the logs are overwritten or deleted. No fixed period applies",
  ],
];

function Privacy() {
  return (
    <LegalPage
      title="Privacy Policy"
      effective="November 24, 2026"
      otherPage={{ to: "/terms", label: "Terms of Service" }}
    >
      <p>
        This policy covers the website recommendosu.com (the &quot;site&quot;),
        which yoshi0428 runs. It tells what the site stores, why, for how long,
        and how to have it removed.
      </p>
      <p className="mb-4">
        The Discord bot has its own{" "}
        <External href="https://github.com/yoshi0428/recommendosu/blob/main/bot/PRIVACY_POLICY.md">
          Privacy Policy
        </External>
        .
      </p>

      <Section title="What the site stores">
        <div className="table-responsive">
          <table className="table mb-0">
            <thead>
              <tr>
                <th scope="col">What</th>
                <th scope="col">When</th>
                <th scope="col">How long</th>
              </tr>
            </thead>
            <tbody>
              {STORED_DATA.map(([what, when, howLong]) => (
                <tr key={what}>
                  <td>{what}</td>
                  <td>{when}</td>
                  <td>{howLong}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Your osu! login">
        <p className="mb-0">
          You log in on the osu! website, so this site never sees your osu!
          password. The site uses the login to know your player ID and to read
          your public scores. It does not change anything on your osu! account.
        </p>
      </Section>

      <Section title="Scores and play history">
        <p>
          The site gets scores from the osu! API to make recommendations. These
          scores are already public on osu!. You can also run the recommender
          for another player. Then, the site stores the public scores of that
          player too.
        </p>
        <p className="mb-0">
          Your play history lets the site hide maps that you already played. The
          site does not store the play history of a different player that you
          look up. The Discord bot uses the same database of scores and play
          history.
        </p>
      </Section>

      <Section title="Clicks and previews">
        <p>The site stores an event when you do one of these things:</p>
        <ul>
          <li>You click the row of a recommendation.</li>
          <li>The audio preview of a recommendation starts.</li>
          <li>
            You open the osu! page of a map from the title of a recommendation.
          </li>
        </ul>
        <p>
          Each event holds your player ID, the player of the recommendations,
          the time, the map, its mods, its position and its recommendation
          score.
        </p>
        <p className="mb-0">
          The site then looks for a play of that map by you in the next 7 days.
          It uses the scores that it stores. Approximately 20 hours after an
          event, it also gets your recent public scores from osu!, even if you
          do not use the site then. If it finds a play, it stores the time, the
          mods and the rank with the event. This data shows which
          recommendations are good, and it is used to improve the recommender.
        </p>
      </Section>

      <Section title="Cookies and browser storage">
        <ul className="mb-0">
          <li>
            The <code>session_id</code> cookie keeps you logged in for at most
            30 days. The site needs it.
          </li>
          <li>
            Your browser stores the volume of the audio preview until you clear
            it.
          </li>
          <li>
            If a page does not load, your browser stores a marker for that tab.
            The marker stops endless reloads.
          </li>
        </ul>
        <p className="mt-3 mb-0">
          The site has no advertising cookies and no third-party analytics.
        </p>
      </Section>

      <Section title="How the data is used">
        <p className="mb-0">
          The data is used to log you in, to make recommendations, to improve
          them, and to fix problems. The data is not sold. It is not used for
          advertising.
        </p>
      </Section>

      <Section title="Who else receives data">
        <ul className="mb-0">
          <li>
            osu! (ppy Pty Ltd): the site sends player IDs and login data to the
            osu! API. Your browser loads map covers and audio previews directly
            from osu! servers. Thus, osu! receives your IP address. See the{" "}
            <External href="https://osu.ppy.sh/legal/en/Privacy">
              osu! privacy policy
            </External>
            .
          </li>
          <li>
            Layer7: this hosting company provides the server that runs the site.
            All the data in the table above is on that server.
          </li>
          <li>
            Links: if you open a link to another site, the policy of that site
            applies.
          </li>
        </ul>
      </Section>

      <Section title="Removing your data">
        <ul className="mb-0">
          <li>
            To delete your current login session and its osu! tokens from the
            server, log out. This does not end your sessions on other devices.
          </li>
          <li>
            To stop the access of the site to your osu! account, remove the app
            in your osu! account settings.
          </li>
          <li>
            To have other data removed, use the contacts below. This includes
            scores, play history, clicks, previews and log entries. You can also
            ask which data the site stores about you.
          </li>
          <li>
            If someone runs the recommender for your account later, the site
            gets your public scores again.
          </li>
        </ul>
      </Section>

      <Section title="Children">
        <p className="mb-0">
          The site is not for children under 13. Obey the minimum age that osu!
          sets too.
        </p>
      </Section>

      <Section title="Changes to this policy">
        <p className="mb-0">
          When this policy changes, this page and its date change too. The
          earlier versions are in the history of the{" "}
          <External href="https://github.com/yoshi0428/recommendosu">
            repository
          </External>
          .
        </p>
      </Section>

      <Contact />
    </LegalPage>
  );
}

export default Privacy;
