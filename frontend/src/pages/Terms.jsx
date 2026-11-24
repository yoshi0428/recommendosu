import { Link } from "react-router-dom";

import LegalPage, { Contact, External, Section } from "../components/LegalPage";

function Terms() {
  return (
    <LegalPage
      title="Terms of Service"
      effective="November 24, 2026"
      otherPage={{ to: "/privacy", label: "Privacy Policy" }}
    >
      <p>
        These terms cover your use of the website recommendosu.com (the
        &quot;site&quot;), which yoshi0428 runs. When you log in to the site,
        you agree to these terms. If you do not agree, do not use the site.
      </p>
      <p className="mb-4">
        The Discord bot has its own{" "}
        <External href="https://github.com/yoshi0428/recommendosu/blob/main/bot/TERMS_OF_SERVICE.md">
          Terms of Service
        </External>
        .
      </p>

      <Section title="What the site does">
        <p className="mb-0">
          The site recommends osu! beatmaps from the public scores of a player.
          You need an osu! account to log in. The{" "}
          <Link to="/privacy">Privacy Policy</Link> tells what the site stores.
        </p>
      </Section>

      <Section title="Using the site">
        <p>You agree that you will not:</p>
        <ul>
          <li>
            send automated requests to the site, or try to get around its
            limits.
          </li>
          <li>
            try to break or overload the site or its server, or try to get
            access to them without permission.
          </li>
          <li>use the login session of another person.</li>
          <li>
            use the site to break the{" "}
            <External href="https://osu.ppy.sh/legal/en/Terms">
              osu! Terms of Service
            </External>
            .
          </li>
        </ul>
        <p className="mb-0">
          If you break these terms or put the site at risk, your access can be
          limited or removed.
        </p>
      </Section>

      <Section title="osu! data">
        <p className="mb-0">
          The player data comes from the osu! API. The beatmap data comes from
          osu! beatmaps. The site is not affiliated with ppy Pty Ltd, and ppy
          Pty Ltd does not endorse it. osu! and its content belong to ppy Pty
          Ltd and the other owners of that content.
        </p>
      </Section>

      <Section title="No guarantees">
        <p>
          The site is a free hobby project. It is provided &quot;as is&quot; and
          &quot;as available&quot;:
        </p>
        <ul className="mb-0">
          <li>
            The site can be offline, slow or changed at any time. It can be shut
            down without notice.
          </li>
          <li>
            The recommendations can be wrong. The star ratings and the pp values
            are estimates.
          </li>
          <li>
            The operator is not liable for any loss or damage from the use of
            the site, or from not being able to use it. This applies as far as
            the law allows.
          </li>
        </ul>
      </Section>

      <Section title="Source code">
        <p className="mb-0">
          The source code is published under the{" "}
          <External href="https://github.com/yoshi0428/recommendosu/blob/main/LICENSE">
            MIT License
          </External>
          . That license covers the code. These terms cover the use of the site.
        </p>
      </Section>

      <Section title="Changes to these terms">
        <p className="mb-0">
          When these terms change, this page and its date change too. If you
          continue to use the site after a change, you accept the new terms. The
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

export default Terms;
