// Injected into the active LinkedIn tab (chrome.scripting.executeScript({ func })) only when the
// user clicks the extension. Reads what is already rendered on screen: no navigation, no scrolling,
// no clicks, no network. Must stay self-contained because Chrome serializes the function.

function collectLinkedInPage(doc, href) {
  doc = doc || document;
  href = href || location.href;
  const NOISE = /^(·|•|\d+(st|nd|rd|th)( degree connection)?|1st|2nd|3rd\+?|view profile|view .*profile|message|connect|follow|following|more|send|pending|see all|show all|premium|try premium.*|\.\.\.)$/i;
  const VIEWED = /\b(viewed|ago|hace|vor|il y a|geleden)\b|^\d+\s*(m|h|d|w|mo|y|yr)s?$/i;
  const isNoise = (t) => t === "·" || t === "•" || NOISE.test(t.replace(/^[·•]\s*/, ""));
  const ANON = /\b(someone|linkedin member|private|anonymous|in the .+ industry|works? at|alguien|jemand|quelqu'un|iemand)\b/i;

  function normalizeProfileUrl(raw) {
    try {
      const u = new URL(raw, "https://www.linkedin.com");
      const m = u.pathname.match(/^\/in\/([^/?#]+)/i);
      if (!/(^|\.)linkedin\.com$/i.test(u.hostname) || !m) return null;
      return `https://www.linkedin.com/in/${decodeURIComponent(m[1]).toLowerCase()}/`;
    } catch {
      return null;
    }
  }

  // LinkedIn's internal member id ("ACoAA…"), present in viewer links (miniProfileUrn query,
  // /in/ACoAA… paths) and data attributes. Lets the app match captures to leads from monitors.
  function memberId(el, rawHref) {
    const hay = [rawHref || ""];
    for (const node of [el, ...el.querySelectorAll("[data-urn],[data-entity-urn],[data-member-id],[href]")]) {
      for (const attr of ["data-urn", "data-entity-urn", "data-member-id", "href"]) {
        const v = node.getAttribute && node.getAttribute(attr);
        if (v) hay.push(v);
      }
    }
    for (const v of hay) {
      const m = decodeURIComponent(v).match(/\b(ACoAA[A-Za-z0-9_-]{10,})\b/);
      if (m) return m[1];
    }
    return null;
  }

  // Visible text lines of an element, in document order. LinkedIn renders many strings twice
  // (aria-hidden copy + visually-hidden copy), so skip hidden copies and collapse repeats.
  function lines(el) {
    const out = [];
    const walker = doc.createTreeWalker(el, 4 /* SHOW_TEXT */);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const parent = node.parentElement;
      if (!parent || parent.closest(".visually-hidden, script, style, button, svg")) continue;
      const text = node.textContent.replace(/\s+/g, " ").trim();
      if (text && out[out.length - 1] !== text) out.push(text);
    }
    return out;
  }

  function pageText(root) {
    const text = typeof root.innerText === "string" ? root.innerText : root.textContent || "";
    return text.replace(/\n{3,}/g, "\n\n").slice(0, 150000);
  }

  const url = new URL(href);
  const main = doc.querySelector("main") || doc.body;

  if (/profile-views/i.test(url.pathname)) {
    const items = [];
    const seen = new Set();
    for (const li of main.querySelectorAll("li")) {
      if (li.querySelector("li")) continue; // only innermost list items
      const anchor = li.querySelector('a[href*="/in/"]');
      const textLines = lines(li).filter((t) => !isNoise(t));
      if (!textLines.length) continue;
      const viewed = textLines.find((t) => VIEWED.test(t)) || null;
      const content = textLines.filter((t) => t !== viewed);
      if (anchor) {
        const profileUrl = normalizeProfileUrl(anchor.getAttribute("href"));
        if (!profileUrl || seen.has(profileUrl)) continue;
        seen.add(profileUrl);
        const name = (content[0] || "").replace(/^view\s+/i, "").replace(/['’]s\s+profile$/i, "").trim();
        items.push({
          name: name || null,
          headline: content[1] || null,
          profile_url: profileUrl,
          member_id: memberId(li, anchor.getAttribute("href")),
          anonymous: false,
          anonymous_hint: null,
          viewed_text: viewed,
        });
      } else if (content.length && content[0].length < 160 && ANON.test(content.join(" "))) {
        const hint = content.slice(0, 2).join(" · ");
        if (seen.has(hint)) continue;
        seen.add(hint);
        items.push({ name: null, headline: null, profile_url: null, member_id: null, anonymous: true, anonymous_hint: hint, viewed_text: viewed });
      }
    }
    return { type: "profile_views", page_url: href, items, page_text: pageText(main) };
  }

  const profileUrl = normalizeProfileUrl(href);
  if (profileUrl) {
    const h1 = main.querySelector("h1");
    const card = (h1 && (h1.closest("section") || h1.parentElement)) || main;
    const cardLines = lines(card).filter((t) => !isNoise(t));
    const name = h1 ? lines(h1).join(" ") : cardLines[0] || null;
    const afterName = cardLines.slice(Math.max(0, cardLines.indexOf(name) + 1));
    const headlineEl = card.querySelector(".text-body-medium");
    const headline = headlineEl ? lines(headlineEl).join(" ") : afterName[0] || null;
    const locationEl = card.querySelector(".text-body-small.inline, .pv-text-details__left-panel .text-body-small");
    const location = locationEl ? lines(locationEl).join(" ") : null;
    const aboutAnchor = main.querySelector("#about");
    const aboutSection = aboutAnchor && aboutAnchor.closest("section");
    const about = aboutSection ? lines(aboutSection).filter((t) => !/^about$/i.test(t)).join(" ").slice(0, 2000) : null;
    return {
      type: "profile",
      page_url: href,
      items: [{ name, headline, profile_url: profileUrl, member_id: memberId(main, href), anonymous: false, anonymous_hint: null, viewed_text: null, location, about }],
      page_text: pageText(main).slice(0, 20000),
    };
  }

  return { type: "unsupported", page_url: href, items: [], page_text: "" };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { collectLinkedInPage };
}
