/* VirtualBuddy site.

   Two things here are worth knowing:

   1. The demo is not a lookup table. It runs the same scoring the app runs:
      hashed word and character n-grams, cosine similarity against every skill
      phrase, plus a bounded bonus for a skill's giveaway words. Type anything
      and it really is the router deciding.

   2. The character is a state machine over the same PNG frames the desktop app
      ships, so it idles, listens while you type, thinks while it routes and
      talks when it answers. */

(() => {
  "use strict";

  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------------------------------------------------------------- themes */
  const THEMES = {
    duck: { accent: "#F0B429", "accent-dim": "#8A6714", base: "#151310",
            surface: "#1D1A15", "surface-hi": "#262118", line: "#332C21",
            text: "#F3EDE2", "text-dim": "#B4AA98", "text-faint": "#78705F",
            lines: ["Quack. Ask me something.", "I run the boring bits.",
                    "48,000 files? Three seconds."] },
    elf:  { accent: "#3FBF87", "accent-dim": "#1E6448", base: "#101613",
            surface: "#161F1B", "surface-hi": "#1D2924", line: "#24332C",
            text: "#E6F0EA", "text-dim": "#9DB0A6", "text-faint": "#66786E",
            lines: ["I read the web so you don't.", "Everything stays on your PC.",
                    "Name a folder. I know it."] },
    crab: { accent: "#FF6B4A", "accent-dim": "#8C3320", base: "#17110F",
            surface: "#211815", "surface-hi": "#2B201B", line: "#382823",
            text: "#F5E9E4", "text-dim": "#BCA79F", "text-faint": "#7E6A63",
            lines: ["Sideways, but efficient.", "Point me at a website.",
                    "Your disk is 89% full, by the way."] },
  };

  const FRAMES = { idle: 2, listening: 3, thinking: 3, talk: 2, working: 4 };
  const PACE = { idle: 620, listening: 260, thinking: 300, talk: 220, working: 180 };

  let avatar = localStorage.getItem("vb-avatar") || "duck";

  function applyTheme(name) {
    const theme = THEMES[name];
    for (const [key, value] of Object.entries(theme)) {
      if (key !== "lines") document.documentElement.style.setProperty(`--${key}`, value);
    }
    document.querySelectorAll("[data-avatar-img]").forEach((img) => {
      img.src = `img/character/${name}/idle_0.png`;
    });
    document.querySelectorAll(".picker button").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.pick === name));
    });
    localStorage.setItem("vb-avatar", name);
  }

  /* ------------------------------------------------------------- character */
  const buddy = document.querySelector(".buddy");
  const bubble = document.querySelector(".bubble");
  let state = "idle", frame = 0, timer = null, revert = null;

  function preload(name) {
    for (const [st, count] of Object.entries(FRAMES)) {
      for (let i = 0; i < count; i++) new Image().src = `img/character/${name}/${st}_${i}.png`;
    }
  }

  const petBox = document.querySelector("#pet");
  const petSprite = document.querySelector(".pet-sprite");
  const petBubble = document.querySelector(".pet-bubble");

  function tick() {
    frame = (frame + 1) % FRAMES[state];
    const src = `img/character/${avatar}/${state}_${frame}.png`;
    if (buddy) buddy.src = src;
    if (petSprite) petSprite.src = src;      // both buddies share one state
    timer = setTimeout(tick, PACE[state]);
  }

  function setState(next, holdMs) {
    if (!buddy) return;
    clearTimeout(revert);
    if (next !== state) { state = next; frame = 0; }
    if (holdMs) revert = setTimeout(() => setState("idle"), holdMs);
  }

  function say(text, ms = 2400) {
    // Whichever buddy the reader can currently see does the talking.
    const target = petBox && petBox.classList.contains("on") ? petBubble : bubble;
    if (!target) return;
    for (const b of [bubble, petBubble]) if (b) b.classList.remove("on");
    target.textContent = text;
    target.classList.add("on");
    setState("talk");
    clearTimeout(say._t);
    say._t = setTimeout(() => { target.classList.remove("on"); setState("idle"); }, ms);
  }

  if (buddy) {
    buddy.addEventListener("click", () => {
      if (!reduced) {
        buddy.classList.remove("hop");
        void buddy.offsetWidth;              // restart the animation
        buddy.classList.add("hop");
      }
      const lines = THEMES[avatar].lines;
      say(lines[Math.floor(Math.random() * lines.length)]);
    });
    buddy.addEventListener("mouseenter", () => setState("listening", 900));

    // The sprite leans toward the pointer. Cheap, and it makes the thing feel
    // aware of you without any physics.
    if (!reduced) {
      addEventListener("pointermove", (e) => {
        const box = buddy.getBoundingClientRect();
        const dx = (e.clientX - (box.left + box.width / 2)) / innerWidth;
        buddy.style.setProperty("rotate", `${Math.max(-7, Math.min(7, dx * 16))}deg`);
      }, { passive: true });
    }
  }

  /* The companion appears once the hero buddy is gone, and can be dragged
     anywhere, which is exactly what it does on a real desktop. */
  if (petBox && petSprite) {
    const hero = document.querySelector(".hero");
    if (hero && "IntersectionObserver" in window) {
      new IntersectionObserver(([entry]) => {
        petBox.classList.toggle("on", !entry.isIntersecting);
        petBox.setAttribute("aria-hidden", String(entry.isIntersecting));
      }, { threshold: 0.25 }).observe(hero);
    }

    let drag = null;
    petSprite.addEventListener("pointerdown", (e) => {
      const box = petBox.getBoundingClientRect();
      drag = { x: e.clientX, y: e.clientY, left: box.left, top: box.top, moved: false };
      petSprite.setPointerCapture(e.pointerId);
    });
    petSprite.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
        drag.moved = true;
        petBox.classList.add("dragging");
        petBox.style.right = "auto";
        petBox.style.bottom = "auto";
        petBox.style.left = `${Math.max(4, Math.min(innerWidth - 100, drag.left + dx))}px`;
        petBox.style.top = `${Math.max(4, Math.min(innerHeight - 100, drag.top + dy))}px`;
      }
    });
    petSprite.addEventListener("pointerup", () => {
      const moved = drag && drag.moved;
      drag = null;
      petBox.classList.remove("dragging");
      if (moved) { say("Good spot.", 1400); return; }
      const lines = THEMES[avatar].lines;
      say(lines[Math.floor(Math.random() * lines.length)]);
    });
    petSprite.addEventListener("mouseenter", () => setState("listening", 900));
  }

  /* ----------------------------------------------------------- the matcher */
  const DIM = 512;

  function hash(str) {                        // FNV-1a
    let h = 0x811c9dc5;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h;
  }

  function encode(text) {
    const vec = new Float32Array(DIM * 2);
    const clean = text.toLowerCase()
      .replace(/https?:\/\/\S+|\b(?:www\.)?[\w-]+\.(?:com|org|net|io|dev|ai|co|in)\b\S*/g, " link ")
      .trim();
    const words = clean.match(/[\w']+/g) || [];
    for (let n = 1; n <= 2; n++) {
      for (let i = 0; i + n <= words.length; i++) {
        vec[hash(words.slice(i, i + n).join(" ")) % DIM] += 1;
      }
    }
    const padded = ` ${clean} `;
    for (let n = 3; n <= 5; n++) {
      for (let i = 0; i + n <= padded.length; i++) {
        vec[DIM + (hash(padded.slice(i, i + n)) % DIM)] += 1;
      }
    }
    let norm = 0;
    for (const v of vec) norm += v * v;
    norm = Math.sqrt(norm) || 1;
    for (let i = 0; i < vec.length; i++) vec[i] /= norm;
    return vec;
  }

  function cosine(a, b) {
    let sum = 0;
    for (let i = 0; i < a.length; i++) sum += a[i] * b[i];
    return sum;
  }

  const SKILLS = [
    { name: "research", args: "topic",
      phrases: ["research the best budget monitors", "do some research on creatine",
                "dig into the news about the election", "compare the best keyboards",
                "brief me on the housing market", "find out everything about rust"],
      triggers: [/\bresearch\b/, /\bdig into\b/, /\bbrief me\b/, /\bcompare\b/],
      out: (q) => `Research: ${q}\n\n- Four sources read, two agreed on price bands\n- Consensus: mid-range wins on value below the flagship tier\n- One outlier review disputes the panel quality claim\n\nSources:\n- rtings.com\n- tomshardware.com\n- reddit.com/r/monitors\n- displayninja.com` },

    { name: "web_search", args: "query",
      phrases: ["search the web for cheap flights", "google the weather in delhi",
                "look up when the shop closes", "find articles about sleep",
                "search for something online"],
      triggers: [/\b(google|search|look up|dig up)\b/, /\bon the (web|internet)\b/],
      out: (q) => `Top results for "${q}":\n\n1. The answer you wanted, probably\n   https://example.com/a\n   Snippet of the page, pulled straight from the results.\n\n2. A second opinion\n   https://example.org/b\n\n3. Documentation, because it always is\n   https://docs.example.net/c` },

    { name: "read_page", args: "url",
      phrases: ["read this link", "summarise this article link", "what does this article say",
                "scrape the text from that link", "give me the gist of this page"],
      triggers: [/\bread\b.{0,20}\b(link|page|article)\b/, /\bsummari[sz]e\b/],
      out: () => `Example Domain\nhttps://example.com  (691 words, via http)\n\n- Page fetched over plain HTTP in 280ms\n- No browser needed, so nothing was downloaded\n- Text extracted with the nav and ads stripped out` },

    { name: "find_file", args: "query",
      phrases: ["find my tax pdf", "where is the invoice spreadsheet",
                "where did i put my resume", "locate my thesis folder",
                "do i have a file about pensions"],
      triggers: [/\bwhere (?:is|are|did)\b/, /\bfind\b/, /\blocate\b/, /\bdo i have\b/],
      out: () => `6 matches for "resume":\n  resume.pdf        90.8KB   29d ago\n    C:\\Users\\you\\Downloads\n  New Resume (2).pdf  131.0KB   16d ago\n    C:\\Users\\you\\Downloads\n  resume.png         6.0KB    5mo ago\n    C:\\Users\\you\\Pictures` },

    { name: "disk_hogs", args: "where",
      phrases: ["what's eating my disk space", "biggest files on my pc",
                "which folders are the largest", "which files are huge",
                "what's filling up my drive"],
      triggers: [/\b(biggest|largest|huge|hogging|eating|filling)\b/, /\btaking up\b/],
      out: () => `Biggest files:\n   21.8GB  Untitled video - Made with Clipchamp.mp4\n    C:\\Users\\you\\Downloads\n    4.4GB  ubuntu-22.04.5-desktop-amd64.iso\n    C:\\Users\\you\\Downloads\n\nHeaviest folders:\n   38.2GB  Downloads (2,481 files)\n   19.4GB  Videos (312 files)` },

    { name: "recent_files", args: "",
      phrases: ["what did i work on today", "recent files", "stuff i edited yesterday",
                "what have i been editing", "files i touched this week"],
      triggers: [/\b(recent|recently|lately|latest|yesterday|this week)\b/,
                 /\b(work(?:ed|ing)? on|edit(?:ed|ing)?|touched|changed)\b/],
      out: () => `Recently changed:\n  graph.py       15.6KB   2min ago\n    C:\\Projects\\VirtualBuddy\\vb\\pc\n  notes.md       1.2KB    3h ago\n    C:\\Users\\you\\Documents\n  invoice.xlsx   44.0KB   yesterday\n    C:\\Users\\you\\Documents\\Work` },

    { name: "whats_in", args: "folder",
      phrases: ["what's in my downloads", "list the desktop folder",
                "peek inside my documents", "what files are in that folder"],
      triggers: [/\b(what'?s?|which files?|contents?)\b.{0,16}\b(in|inside)\b/,
                 /\b(peek|look)\b.{0,10}\b(in|inside)\b/],
      out: () => `C:\\Users\\you\\Downloads\n31 folders, 271 files\n\nFolders:\n  installers/\n  invoices/\n  screenshots/\n\nFiles:\n  setup.exe        84.1MB   2d ago\n  ticket.pdf       210KB    6d ago` },

    { name: "create_file", args: "name",
      phrases: ["create a file called notes.txt on my desktop",
                "make a new text file in documents saying remember the milk",
                "new file called todo.md", "start a new document called ideas"],
      triggers: [/\b(create|make|new|start|write)\b.{0,20}\b(file|document|note)\b/],
      out: () => `Created C:\\Users\\you\\Desktop\\notes.txt  (18 characters)` },

    { name: "edit_file", args: "name",
      phrases: ["add a line to notes.txt saying call mum", "append to my todo list buy milk",
                "in notes.txt replace monday with tuesday", "edit the shopping list"],
      triggers: [/\b(append|add|stick)\b.{0,30}\b(to|in|into)\b/, /\breplace\b.+\bwith\b/],
      out: () => `Added to notes.txt: "call mum"\nC:\\Users\\you\\Desktop\\notes.txt` },

    { name: "running_apps", args: "",
      phrases: ["what's running on my pc", "what's using my cpu", "why is my pc slow",
                "what's hogging the cpu right now", "open task manager"],
      triggers: [/\b(cpu|ram|memory|task manager|processes?)\b/, /\bwhy is\b.{0,16}\bslow\b/],
      out: () => `CPU 16%  ·  RAM 94% of 15.3GB  ·  412 processes\n\nTop CPU:\n   6.6%  dwm.exe\n   5.2%  chrome.exe  ×14\n   1.3%  System\n\nTop memory:\n   3.1GB  chrome.exe\n   1.4GB  Code.exe` },

    { name: "pc_health", args: "",
      phrases: ["check my battery", "how much disk space is left", "system status",
                "how long has this pc been on"],
      triggers: [/\bbattery\b/, /\buptime\b/, /\bdisk space\b/],
      out: () => `RAM    90% used of 15.3GB  (1.5GB free)\nDisk   C:\\  89% used, 103.4GB free of 952.8GB\nPower  95% (charging)\nUptime 0d 20h 34m` },

    { name: "open_app", args: "target",
      phrases: ["open chrome", "launch spotify", "start the calculator", "fire up vs code"],
      triggers: [/^\s*(open|launch|start|run|fire up)\b/],
      out: (q) => `Opened ${q || "chrome"}.` },

    { name: "add_task", args: "text",
      phrases: ["remind me to call the dentist tomorrow", "add buy milk to my todo list",
                "jot down pick up the parcel on saturday"],
      triggers: [/\bremind me\b/, /\bjot down\b/, /\b(add|put)\b.{0,30}\b(todo|task|list)\b/],
      out: (q) => `Added: ${q || "call the dentist"} (tomorrow)\n2 open tasks.` },

    { name: "list_tasks", args: "",
      phrases: ["what's on my todo list", "show my tasks", "what do i need to do",
                "what's left for me to do today"],
      triggers: [/\b(todo|to-do|to do)\b/, /\bmy (tasks|list)\b/],
      out: () => `2 open:\n  1. call the dentist   ·  tomorrow\n  2. pick up parcel     ·  in 2d` },

    { name: "index_pc", args: "",
      phrases: ["index my pc", "scan my computer", "rebuild the file index",
                "scan everything on this machine"],
      triggers: [/\b(index|reindex)\b/, /\bscan\b.*\b(pc|computer|machine|files)\b/],
      out: () => `Indexed 48,787 files in 2,979 folders (2.7s).\n\nRoots:\n  C:\\Users\\you\\Desktop\n  C:\\Users\\you\\Documents\n  C:\\Users\\you\\Downloads\n  C:\\Projects` },
  ];

  // Encode every phrase once, at load.
  for (const skill of SKILLS) skill.vectors = skill.phrases.map(encode);

  const BONUS = 0.22, EXTRA = 0.08, CAP = 0.34, FLOOR = 0.22;

  function route(text) {
    const query = encode(text);
    const clean = text.toLowerCase();
    let best = null;
    for (const skill of SKILLS) {
      let score = 0;
      for (const vec of skill.vectors) score = Math.max(score, cosine(vec, query));
      const hits = skill.triggers.filter((rx) => rx.test(clean)).length;
      if (hits) score = Math.min(1, score + Math.min(BONUS + (hits - 1) * EXTRA, CAP));
      if (!best || score > best.score) best = { skill, score };
    }
    return best && best.score >= FLOOR ? best : null;
  }

  /* --------------------------------------------------------------- the demo */
  const input = document.querySelector("#ask");
  const runBtn = document.querySelector("#run");
  const matchRow = document.querySelector(".match");
  const matchName = document.querySelector(".match .who b");
  const matchArgs = document.querySelector(".match .who span");
  const fill = document.querySelector(".meter .fill");
  const val = document.querySelector(".meter .val");
  const out = document.querySelector(".out");

  function argOf(text, skill) {
    const stripped = text
      .replace(/^(hey |buddy |please |can you |could you )+/i, "")
      .replace(/^(search the web for|search for|google|look up|research|find out about|find|open|launch|read|index|remind me to|add|jot down)\s+/i, "")
      .trim();
    return stripped || skill.phrases[0];
  }

  function show(text) {
    const hit = route(text);
    if (!hit) {
      matchRow.style.visibility = "hidden";
      out.innerHTML = `<b class="head">No skill for that yet.</b>Try: research the best budget monitors, where did i put my resume, or what's using my cpu.`;
      setState("idle");
      return;
    }
    const { skill, score } = hit;
    matchRow.style.visibility = "visible";
    matchName.textContent = skill.name.replace(/_/g, " ");
    matchArgs.textContent = skill.args ? `${skill.args}=${argOf(text, skill)}` : "no arguments";
    fill.style.width = `${Math.round(score * 100)}%`;
    val.textContent = score.toFixed(2);

    setState("thinking");
    out.innerHTML = `<b class="head">Working…</b>`;
    setTimeout(() => {
      setState("working");
      setTimeout(() => {
        const body = skill.out(argOf(text, skill));
        const [head, ...rest] = body.split("\n");
        out.innerHTML = "";
        const h = document.createElement("b");
        h.className = "head";
        h.textContent = head;
        out.append(h, document.createTextNode(rest.join("\n")));
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = "sample output";
        out.append(tag);
        say("Done.", 1600);
      }, reduced ? 0 : 620);
    }, reduced ? 0 : 380);
  }

  if (input) {
    input.addEventListener("input", () => setState(input.value ? "listening" : "idle", 1200));
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") show(input.value.trim()); });
    runBtn.addEventListener("click", () => show(input.value.trim()));
    document.querySelectorAll(".tries button").forEach((b) => {
      b.addEventListener("click", () => {
        const text = b.textContent;
        input.value = "";
        typeOut(text, () => show(text));
      });
    });
  }

  function typeOut(text, done) {
    if (reduced) { input.value = text; done(); return; }
    let i = 0;
    setState("listening");
    (function step() {
      input.value = text.slice(0, ++i);
      if (i < text.length) setTimeout(step, 22);
      else done();
    })();
  }

  /* --------------------------------------------------------------- chrome */
  document.querySelectorAll(".picker button").forEach((b) => {
    b.addEventListener("click", () => {
      avatar = b.dataset.pick;
      applyTheme(avatar);
      preload(avatar);
      frame = 0;
      say(THEMES[avatar].lines[0]);
    });
  });

  document.querySelectorAll(".copy").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const code = btn.closest("pre").innerText.replace(/^copy$/gm, "").trim();
      try {
        await navigator.clipboard.writeText(code);
        btn.textContent = "copied";
        setTimeout(() => (btn.textContent = "copy"), 1600);
      } catch { btn.textContent = "select it"; }
    });
  });

  if (!reduced && "IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) { entry.target.classList.add("in"); io.unobserve(entry.target); }
      }
    }, { threshold: 0.15 });
    document.querySelectorAll(".reveal").forEach((el) => io.observe(el));
  } else {
    document.querySelectorAll(".reveal").forEach((el) => el.classList.add("in"));
  }

  applyTheme(avatar);
  preload(avatar);
  if (buddy && !reduced) tick();

  // A quiet hello, once the page has settled.
  setTimeout(() => { if (buddy) say(THEMES[avatar].lines[0], 3000); }, 1800);
})();
