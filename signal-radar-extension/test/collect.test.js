const { test } = require("node:test");
const assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const { collectLinkedInPage } = require("../collect.js");

function run(html, url) {
  const dom = new JSDOM(`<!doctype html><body>${html}</body>`, { url });
  return collectLinkedInPage(dom.window.document, url);
}

// Mimics LinkedIn's markup: aria-hidden + visually-hidden duplicates, buttons, a nested list.
const viewer = (slug, name, headline, when) => `
  <li class="member-analytics-addon-entity-list__item">
    <a href="/in/${slug}/?miniProfileUrn=abc" class="optional-action-target-wrapper">
      <span aria-hidden="true">${name}</span><span class="visually-hidden">${name}</span>
      <span class="dist"> · 2nd</span>
    </a>
    <div><span aria-hidden="true">${headline}</span><span class="visually-hidden">${headline}</span></div>
    <div><span>${when}</span></div>
    <button><span>Connect</span></button>
  </li>`;

const VIEWERS = `
  <main>
    <h1>Who viewed your profile</h1>
    <ul>
      ${viewer("ana-ruiz-1a2b", "Ana Ruiz", "Head of Trade Marketing at Danone", "Viewed 2h ago")}
      ${viewer("Tom-Berg", "Tom Berg", "Field Sales Manager at Heineken", "Viewed 1d ago")}
      ${viewer("ana-ruiz-1a2b", "Ana Ruiz", "Head of Trade Marketing at Danone", "Viewed 3d ago")}
      <li><div><span>Someone at Unilever</span></div><div><span>Viewed 5d ago</span></div></li>
      <li><div><span>Founder in the Food &amp; Beverage Services industry</span></div></li>
      <li><ul><li><span>Nested promo, not a viewer</span></li></ul></li>
      <li><span>Try Premium for free</span></li>
    </ul>
  </main>`;

test("profile viewers: people, anonymous viewers, dedupe and noise filtering", () => {
  const r = run(VIEWERS, "https://www.linkedin.com/analytics/profile-views/");
  assert.equal(r.type, "profile_views");
  const people = r.items.filter((i) => !i.anonymous);
  const anon = r.items.filter((i) => i.anonymous);
  assert.deepEqual(people.map((p) => p.profile_url), [
    "https://www.linkedin.com/in/ana-ruiz-1a2b/",
    "https://www.linkedin.com/in/tom-berg/",
  ]);
  assert.equal(people[0].name, "Ana Ruiz");
  assert.equal(people[0].headline, "Head of Trade Marketing at Danone");
  assert.equal(people[0].viewed_text, "Viewed 2h ago");
  assert.equal(anon.length, 2);
  assert.match(anon[0].anonymous_hint, /Someone at Unilever/);
  assert.match(anon[1].anonymous_hint, /Food & Beverage/);
  assert.ok(r.page_text.includes("Who viewed your profile"));
});

test("old /me/profile-views/ URL is supported too", () => {
  const r = run(VIEWERS, "https://www.linkedin.com/me/profile-views/");
  assert.equal(r.type, "profile_views");
  assert.equal(r.items.filter((i) => !i.anonymous).length, 2);
});

test("single profile page", () => {
  const html = `
    <main>
      <section class="artdeco-card">
        <h1>María José García</h1>
        <div class="text-body-medium break-words">Category Manager at Mahou San Miguel</div>
        <span class="text-body-small inline">Madrid, Community of Madrid, Spain</span>
        <button>Message</button>
      </section>
      <section><div id="about"></div><h2><span aria-hidden="true">About</span></h2>
        <div><span aria-hidden="true">15 years in FMCG category management and retail execution.</span></div>
      </section>
    </main>`;
  const r = run(html, "https://www.linkedin.com/in/maria-jose-garcia/details/experience/?x=1");
  assert.equal(r.type, "profile");
  assert.equal(r.items.length, 1);
  const p = r.items[0];
  assert.equal(p.profile_url, "https://www.linkedin.com/in/maria-jose-garcia/");
  assert.equal(p.name, "María José García");
  assert.equal(p.headline, "Category Manager at Mahou San Miguel");
  assert.equal(p.location, "Madrid, Community of Madrid, Spain");
  assert.match(p.about, /retail execution/);
});

test("unsupported LinkedIn pages send nothing", () => {
  const r = run("<main><h1>Feed</h1></main>", "https://www.linkedin.com/feed/");
  assert.equal(r.type, "unsupported");
  assert.equal(r.items.length, 0);
});

test("the function is self-contained (Chrome serializes it for injection)", () => {
  const src = collectLinkedInPage.toString();
  // Rebuild from source text alone, as chrome.scripting does, and run it.
  const rebuilt = new Function(`return (${src})`)();
  const dom = new JSDOM(`<!doctype html><body>${VIEWERS}</body>`, { url: "https://www.linkedin.com/analytics/profile-views/" });
  const r = rebuilt(dom.window.document, dom.window.location.href);
  assert.equal(r.items.length, 4);
});
