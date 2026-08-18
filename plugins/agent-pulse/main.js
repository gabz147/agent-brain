'use strict';

/*
 * Agent Pulse
 *
 * Two icons placed immediately after the Bookmarks tab header in the left
 * sidebar's tab strip (Files | Search | Bookmarks | <these two>):
 *   1. A refresh button that soft-reloads the open markdown panes in place
 *      so external agent edits appear — with a brief fade and one spin of
 *      the icon — and NO full app:reload (which tore the whole window down
 *      and rebuilt it, the visible collapse/respring).
 *   2. An 8-dot ring "orb" whose animation state (idle / agent-present /
 *      active) reflects whether a background coding agent has recently
 *      touched the vault, tripped the vault-automation stop gate, queued
 *      work, or is holding the drain lock.
 *
 * Both icons are created via addRibbonIcon() (so Obsidian still owns their
 * lifecycle/teardown) and then relocated in the DOM. If the Bookmarks tab
 * header isn't found (sidebar collapsed, Bookmarks core plugin disabled,
 * not yet rendered), they fall back to the original ribbon placement
 * immediately after the Bookmarks ribbon icon, or grouped at the top of
 * the ribbon if that's absent too (Obsidian 1.13.4 has no Bookmarks ribbon
 * icon at all, so this fallback is the common case there).
 *
 * No build step, no npm dependencies. Hand-written CommonJS, desktop-only
 * (uses Node's fs/child_process, available under Electron).
 */

const { Plugin, setTooltip } = require('obsidian');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { exec } = require('child_process');

// ---------------------------------------------------------------------
// Signal-source paths. The automation dir is machine-specific, so it is
// driven by the same BRAIN_AUTOMATION_DIR env var the rest of agent-brain
// uses, falling back to ~/.claude/vault-automation. If the automation
// module isn't installed the dir simply won't exist, and every poll below
// treats a missing file as "no signal" (never an error) — so the orb just
// stays idle and the refresh button still works.
// ---------------------------------------------------------------------
const AUTOMATION_DIR =
  process.env.BRAIN_AUTOMATION_DIR || path.join(os.homedir(), '.claude', 'vault-automation');
const STOP_STATE_PATH = path.join(AUTOMATION_DIR, 'stop-state.json');
const QUEUE_PATH = path.join(AUTOMATION_DIR, 'queue.jsonl');
const QUEUE_BATCH_PATH = path.join(AUTOMATION_DIR, 'queue.batch.jsonl');
const DRAIN_LOCK_PATH = path.join(AUTOMATION_DIR, '.drain.lock');

// ---------------------------------------------------------------------
// Timing constants.
// ---------------------------------------------------------------------
const VAULT_WRITE_ACTIVE_MS = 45000; // a vault .md write counts as "active" for this long
const AUTOMATION_FRESH_MS = 60000; // stop-state / queue freshness window
const FS_POLL_MS = 5000; // fs.promises.stat poll interval (>=5000ms required)
const PROCESS_POLL_MS = 60000; // tasklist poll interval (60s only, never per-second)
const PROCESS_SIGNAL_STALE_MS = PROCESS_POLL_MS * 3; // stop trusting agentProcessAlive if not refreshed within this window
const VAULT_WARMUP_MS = 3000; // ignore vault events for this long after handlers are registered

// ---------------------------------------------------------------------
// The orb markup (8 dots evenly spaced on a ring, per orb-visual-spec.md
// section 2.1). Built once; plugin JS afterwards only ever toggles the
// container's is-idle / is-agent-present / is-active class.
// ---------------------------------------------------------------------
const ORB_SVG_MARKUP = [
  '<svg class="apo-svg" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">',
  '<g class="apo-ring">',
  '<circle class="apo-dot" style="--n:0" cx="12" cy="4" r="1.6"/>',
  '<circle class="apo-dot" style="--n:1" cx="17.66" cy="6.34" r="1.6"/>',
  '<circle class="apo-dot" style="--n:2" cx="20" cy="12" r="1.6"/>',
  '<circle class="apo-dot" style="--n:3" cx="17.66" cy="17.66" r="1.6"/>',
  '<circle class="apo-dot" style="--n:4" cx="12" cy="20" r="1.6"/>',
  '<circle class="apo-dot" style="--n:5" cx="6.34" cy="17.66" r="1.6"/>',
  '<circle class="apo-dot" style="--n:6" cx="4" cy="12" r="1.6"/>',
  '<circle class="apo-dot" style="--n:7" cx="6.34" cy="6.34" r="1.6"/>',
  '</g>',
  '</svg>',
].join('');

// ---------------------------------------------------------------------
// computeState — the signal engine. PURE function of (signals, now).
// No I/O in here, so it is unit-testable without Obsidian.
//
// signals shape:
//   {
//     lastVaultWriteMs: number|null,     // last non-editor .md vault write
//     stopStateMs: number|null,          // freshest of stop-state.json mtime / lastFiredMs
//     queueMs: number|null,              // newer of queue.jsonl / queue.batch.jsonl mtime
//     drainLockHeld: boolean|null,       // .drain.lock currently held (null = unknown)
//     agentProcessAlive: boolean|null,   // claude.exe / codex.exe alive (null = unknown)
//     agentProcessCheckedMs: number|null,// when agentProcessAlive was last successfully
//                                        // refreshed by a tasklist poll (null = never/unknown)
//   }
// ---------------------------------------------------------------------

// A timestamp-derived age that is never allowed to look "fresh" because of a
// clock-skewed or future-dated source (negative age). Missing/invalid
// timestamps and future timestamps both collapse to Infinity (i.e. stale).
function safeAgeMs(tsMs, now) {
  if (typeof tsMs !== 'number' || Number.isNaN(tsMs)) return Infinity;
  const age = now - tsMs;
  return age < 0 ? Infinity : age;
}

// Trust agentProcessAlive only while it has been refreshed recently.
// agentProcessCheckedMs is optional (older callers/tests may omit it);
// when present, a stale or future-dated check means "don't know" rather
// than holding the last-seen value forever.
function isProcessSignalStale(agentProcessCheckedMs, now) {
  const hasCheckedMs = typeof agentProcessCheckedMs === 'number' && !Number.isNaN(agentProcessCheckedMs);
  if (!hasCheckedMs) return false;
  const ageMs = now - agentProcessCheckedMs;
  return ageMs < 0 || ageMs >= PROCESS_SIGNAL_STALE_MS;
}

// True while an incoming vault event still falls inside the post-registration
// warm-up window. Obsidian fires vault.on('create', ...) once for every
// pre-existing file while the vault first loads; registering the handlers
// inside onLayoutReady (see onload()) narrows that flood but does not fully
// bound it on a large vault, so this is the second layer: anything that
// arrives within VAULT_WARMUP_MS of registration is still initial-indexing
// noise, not a real write, and must be ignored.
function isWithinVaultWarmup(nowMs, registeredAtMs) {
  if (typeof registeredAtMs !== 'number' || Number.isNaN(registeredAtMs)) return false;
  return nowMs - registeredAtMs < VAULT_WARMUP_MS;
}

function computeState(signals, now) {
  const s = signals || {};

  const vaultAgeMs = safeAgeMs(s.lastVaultWriteMs, now);
  const stopAgeMs = safeAgeMs(s.stopStateMs, now);
  const queueAgeMs = safeAgeMs(s.queueMs, now);

  const isActive =
    vaultAgeMs < VAULT_WRITE_ACTIVE_MS ||
    stopAgeMs < AUTOMATION_FRESH_MS ||
    queueAgeMs < AUTOMATION_FRESH_MS ||
    !!s.drainLockHeld;

  if (isActive) return 'active';

  const processFresh = !isProcessSignalStale(s.agentProcessCheckedMs, now);
  if (s.agentProcessAlive && processFresh) return 'agent-present';
  return 'idle';
}

function formatRelative(deltaMs) {
  if (!(typeof deltaMs === 'number') || Number.isNaN(deltaMs) || deltaMs < 0) return 'just now';
  const secs = Math.floor(deltaMs / 1000);
  if (secs < 1) return 'just now';
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

class AgentPulsePlugin extends Plugin {
  async onload() {
    this._signals = {
      lastVaultWriteMs: null,
      stopStateMs: null,
      queueMs: null,
      drainLockHeld: false,
      agentProcessAlive: null,
      agentProcessCheckedMs: null,
    };
    this._lastTouchedFile = null;
    this._currentState = 'idle';

    this._repositioning = false;
    this._ribbonObserver = null;
    this._ribbonObserverRegistered = false;
    this._observedContainerEl = null;
    this._tabStripObserver = null;
    this._tabStripObserverRegistered = false;
    this._observedTabStripContainerEl = null;
    this._orbEl = null;
    this._refreshEl = null;
    this._unloaded = false;
    this._vaultHandlersRegisteredMs = null;

    this.app.workspace.onLayoutReady(() => {
      // onLayoutReady's callback is not tied to this.register(); if the
      // plugin is disabled before layout readiness fires, this must become
      // a no-op instead of mounting icons / starting an observer after
      // onunload() already ran.
      if (this._unloaded) return;
      this.mountRibbonIcons();
      this.repositionIcons();
      this.watchRibbon();
      this.watchTabStrip();

      // Vault write signals — registered here, not at onload top level,
      // because Obsidian fires vault.on('create', ...) once for every
      // pre-existing file during initial vault indexing. Registering inside
      // onLayoutReady avoids most of that flood; handleVaultEvent()'s
      // VAULT_WARMUP_MS check (using the timestamp recorded here) is the
      // second layer for whatever indexing still trails past layout-ready
      // on a large vault. Also excludes the file currently open in the
      // active editor so the user's own typing never lights the orb.
      this._vaultHandlersRegisteredMs = Date.now();
      this.registerEvent(this.app.vault.on('modify', (file) => this.handleVaultEvent(file)));
      this.registerEvent(this.app.vault.on('create', (file) => this.handleVaultEvent(file)));
      this.registerEvent(this.app.vault.on('delete', (file) => this.handleVaultEvent(file)));

      this.refreshUI();
    });

    // Redundant safety net for whole-container re-renders (see
    // ribbon-technique.md §4, mirrored for the tab strip). Also re-checks
    // whether Obsidian swapped in a new ribbon/tab-strip container; if so,
    // the observer watching the old (now detached) container is reattached
    // to the live one so mutations there are not silently missed. This is
    // also what self-heals a collapsed-then-reexpanded left sidebar, since
    // the tab strip is removed from the DOM entirely while collapsed (its
    // MutationObserver can't see that — the target itself isn't mutating,
    // its parent is) and layout-change is the only signal left.
    this.registerEvent(
      this.app.workspace.on('layout-change', () => {
        this.repositionIcons();
        this.ensureRibbonObserverAttached();
        this.ensureTabStripObserverAttached();
      })
    );

    // Automation-file freshness, polled async every 5s (never sync, never faster).
    this.registerInterval(
      window.setInterval(() => {
        this.pollAutomationFiles();
      }, FS_POLL_MS)
    );

    // Process liveness, polled async every 60s only.
    this.registerInterval(
      window.setInterval(() => {
        this.pollProcesses();
      }, PROCESS_POLL_MS)
    );

    // Prime both so the orb isn't blank on first paint.
    this.pollAutomationFiles();
    this.pollProcesses();
  }

  onunload() {
    this._unloaded = true;

    this._ribbonObserver?.disconnect();
    this._ribbonObserver = null;
    this._observedContainerEl = null;

    this._tabStripObserver?.disconnect();
    this._tabStripObserver = null;
    this._observedTabStripContainerEl = null;

    if (this._orbEl && this._orbEl.remove) this._orbEl.remove();
    if (this._refreshEl && this._refreshEl.remove) this._refreshEl.remove();
    this._orbEl = null;
    this._refreshEl = null;
  }

  // -------------------------------------------------------------
  // Ribbon mounting + positioning (ribbon-technique.md, faithfully
  // ported: same anchor lookup, same two-layer loop guard).
  // -------------------------------------------------------------

  mountRibbonIcons() {
    if (!this._orbEl) {
      this._orbEl = this.addRibbonIcon('circle', 'Agent Pulse', () => {
        // Manual nudge: re-poll automation files immediately on click.
        this.pollAutomationFiles();
      });
      this._orbEl.addClass('agent-pulse-orb');
      this._orbEl.addClass('is-idle');
      this._orbEl.innerHTML = ORB_SVG_MARKUP;
    }

    if (!this._refreshEl) {
      this._refreshEl = this.addRibbonIcon(
        'refresh-cw',
        'Refresh panes (pick up agent edits)',
        () => this.softRefresh()
      );
    }
  }

  // Soft refresh — reload the open markdown panes in place so external agent
  // edits show up, WITHOUT app:reload. app:reload restarts Obsidian's entire
  // renderer, which is exactly what produced the full-window collapse and
  // respring. rebuildView() re-reads each markdown leaf's file from disk with
  // no window teardown; a short fade on each refreshed pane plus one spin of
  // the button icon give a deliberate "it updated" cue. All motion is
  // opacity/transform only (compositor-driven, so it rides the monitor's
  // refresh rate automatically) and is frozen under prefers-reduced-motion in
  // styles.css. A pane that can't rebuild is skipped, never fatal.
  softRefresh() {
    if (this._refreshEl && this._refreshEl.addClass) {
      this._refreshEl.addClass('agent-pulse-spin');
      window.setTimeout(() => {
        if (this._refreshEl && this._refreshEl.removeClass) this._refreshEl.removeClass('agent-pulse-spin');
      }, 520);
    }

    const leaves = this.app.workspace.getLeavesOfType('markdown');
    for (const leaf of leaves) {
      try {
        if (typeof leaf.rebuildView === 'function') leaf.rebuildView();
      } catch (_) {
        // One pane failing to rebuild must not abort refreshing the rest.
      }
      const el = (leaf.view && (leaf.view.contentEl || leaf.view.containerEl)) || leaf.containerEl;
      if (el && el.addClass) {
        el.removeClass('agent-pulse-fade-in');
        void el.offsetWidth; // force reflow so re-adding the class restarts the animation
        el.addClass('agent-pulse-fade-in');
        window.setTimeout(() => {
          if (el.removeClass) el.removeClass('agent-pulse-fade-in');
        }, 320);
      }
    }

    // Re-poll automation files so the orb reflects current state immediately.
    this.pollAutomationFiles();
  }

  getRibbonContainer() {
    // Prefer the private-but-precise workspace field; fall back to a
    // version-agnostic CSS selector if it's gone in a future release.
    return (
      this.app.workspace.leftRibbon?.ribbonItemsEl ||
      document.querySelector('.workspace-ribbon.mod-left .side-dock-actions') ||
      document.querySelector('.side-dock-ribbon .side-dock-actions')
    );
  }

  findBookmarksButton(containerEl) {
    if (!containerEl) return null;
    let btn = containerEl.querySelector('.side-dock-ribbon-action[aria-label="Bookmarks"]');
    if (btn) return btn;
    btn = Array.from(containerEl.querySelectorAll('.side-dock-ribbon-action')).find((el) =>
      el.querySelector('svg.lucide-bookmark')
    );
    return btn || null;
  }

  // The Bookmarks *tab header* in the left sidebar's tab strip (Files |
  // Search | Bookmarks), NOT the ribbon icon — Obsidian 1.13.4 has no
  // Bookmarks ribbon icon at all. data-type is used, not aria-label:
  // aria-label is the localized display string, data-type is not.
  findBookmarksTab() {
    return document.querySelector(
      '.workspace-tab-header-container-inner .workspace-tab-header[data-type="bookmarks"]'
    );
  }

  // General (anchor-independent) lookup for the left sidebar's tab-strip
  // container, used to (re)attach the MutationObserver even when the
  // Bookmarks tab itself isn't currently present (e.g. its core plugin is
  // disabled) so we still notice if/when it reappears. Prefers the live
  // anchor's actual parent when available — that's the precise container
  // repositionInTabStrip() just wrote into.
  getTabStripContainer() {
    const bookmarksTab = this.findBookmarksTab();
    if (bookmarksTab && bookmarksTab.parentElement) return bookmarksTab.parentElement;
    return document.querySelector('.workspace-split.mod-left-split .workspace-tab-header-container-inner');
  }

  repositionIcons() {
    // Same-stack re-entry guard only — cannot and does not suppress the
    // MutationObserver callback for our own writes (that's handled below
    // via takeRecords(), synchronously, in the finally block).
    if (this._repositioning) return;
    if (!this._orbEl || !this._refreshEl) return;

    this._repositioning = true;
    try {
      // Primary: sit immediately right of the Bookmarks tab header. Only
      // fall back to the ribbon (unchanged legacy behaviour) when that
      // anchor genuinely isn't there right now (sidebar collapsed,
      // Bookmarks core plugin disabled, or not yet rendered) — this is
      // treated as a normal, recoverable state, not an error.
      const placedInTabStrip = this.repositionInTabStrip();
      if (!placedInTabStrip) {
        this.repositionInRibbon();
      }
    } finally {
      // The loop guard: drain our own just-queued mutation records while
      // still synchronous, so they are never delivered to either observer
      // callback. A single move can touch both containers (removed from
      // one, added to the other), so both must be drained here regardless
      // of which path just ran.
      this._ribbonObserver?.takeRecords();
      this._tabStripObserver?.takeRecords();
      this._repositioning = false;
    }
  }

  // Anchor: Bookmarks tab header. Places refresh immediately after it, then
  // the orb immediately after refresh, inside
  // .workspace-tab-header-container-inner. Returns true if the anchor was
  // found and the icons live there now; false if the caller should fall
  // back to the ribbon.
  repositionInTabStrip() {
    const bookmarksTab = this.findBookmarksTab();
    if (!bookmarksTab || !bookmarksTab.parentElement) return false;

    for (const el of [this._refreshEl, this._orbEl]) {
      if (!el.hasClass('agent-pulse-in-tabstrip')) el.addClass('agent-pulse-in-tabstrip');
    }

    const mine = [this._refreshEl, this._orbEl];
    let anchor = bookmarksTab;
    for (const el of mine) {
      // Idempotency check: already directly after the anchor -> no write.
      if (el.previousElementSibling !== anchor) {
        anchor.insertAdjacentElement('afterend', el);
      }
      anchor = el;
    }
    return true;
  }

  // Legacy ribbon placement (ribbon-technique.md), used only as the
  // fallback when the Bookmarks tab header isn't found. Unchanged from the
  // pre-tab-strip behaviour, aside from stripping the tab-strip styling
  // marker so the icons don't keep the tab-sized look while in the ribbon.
  repositionInRibbon() {
    const containerEl = this.getRibbonContainer();
    if (!containerEl) return;

    for (const el of [this._refreshEl, this._orbEl]) {
      if (el.hasClass('agent-pulse-in-tabstrip')) el.removeClass('agent-pulse-in-tabstrip');
    }

    // Spec order: Bookmarks -> refresh -> orb (refresh immediately right of
    // Bookmarks, orb to the right of that). This array's order IS the
    // placement order for both the anchored path and the Bookmarks-absent
    // fallback path below.
    const mine = [this._refreshEl, this._orbEl];
    const bookmarksBtn = this.findBookmarksButton(containerEl);

    let anchor = bookmarksBtn;
    if (anchor) {
      for (const el of mine) {
        // Idempotency check: already directly after the anchor -> no write.
        if (el.previousElementSibling !== anchor) {
          anchor.insertAdjacentElement('afterend', el);
        }
        anchor = el;
      }
    } else {
      // Degradation path: no Bookmarks button found. Group at the top
      // of the ribbon instead of leaving default append order.
      anchor = null;
      for (const el of mine) {
        if (anchor === null) {
          // FIRST icon, no anchor. Must check "already the container's
          // first child", not previousElementSibling === null — prepend()
          // on an already-first node still detaches+reattaches it,
          // emitting mutation records forever if skipped.
          if (containerEl.firstElementChild !== el) containerEl.prepend(el);
        } else if (el.previousElementSibling !== anchor) {
          anchor.insertAdjacentElement('afterend', el);
        }
        anchor = el;
      }
    }
  }

  watchRibbon() {
    const containerEl = this.getRibbonContainer();
    if (!containerEl) return;
    this._ribbonObserver?.disconnect();
    // No `_repositioning` check in here: by the time this microtask runs,
    // the flag is always false. Self-inflicted records are already gone,
    // discarded by takeRecords() above.
    this._ribbonObserver = new MutationObserver(() => this.repositionIcons());
    this._ribbonObserver.observe(containerEl, { childList: true });
    this._observedContainerEl = containerEl;
    // Register the disconnect-on-unload cleanup once. It closes over
    // `this`, not a captured observer variable, so it always disconnects
    // whichever observer is current at unload time — re-registering on
    // every re-attach would just accumulate redundant no-op callbacks.
    if (!this._ribbonObserverRegistered) {
      this._ribbonObserverRegistered = true;
      this.register(() => this._ribbonObserver?.disconnect());
    }
  }

  // Same pattern as watchRibbon(), mirrored onto the tab-strip container.
  watchTabStrip() {
    const containerEl = this.getTabStripContainer();
    if (!containerEl) return;
    this._tabStripObserver?.disconnect();
    // No `_repositioning` check in here, same reasoning as watchRibbon():
    // self-inflicted records are already drained synchronously above.
    this._tabStripObserver = new MutationObserver(() => this.repositionIcons());
    this._tabStripObserver.observe(containerEl, { childList: true });
    this._observedTabStripContainerEl = containerEl;
    if (!this._tabStripObserverRegistered) {
      this._tabStripObserverRegistered = true;
      this.register(() => this._tabStripObserver?.disconnect());
    }
  }

  // Obsidian occasionally replaces the whole ribbon container element (not
  // just its children) on a layout re-render. When that happens, our
  // MutationObserver keeps watching the detached old container forever and
  // the live one goes unwatched. Called on every 'layout-change'; cheap
  // (one DOM lookup + reference compare) and idempotent.
  ensureRibbonObserverAttached() {
    const containerEl = this.getRibbonContainer();
    if (containerEl && containerEl !== this._observedContainerEl) {
      this.watchRibbon();
    }
  }

  // Same pattern as ensureRibbonObserverAttached(), mirrored onto the
  // tab-strip container. This is also the mechanism that re-attaches after
  // a collapsed-then-reexpanded left sidebar: the tab strip is removed
  // from the DOM outright while collapsed (see repositionIcons()), so the
  // MutationObserver watching the old, now-detached container never fires
  // on its own — this layout-change-driven recheck is what notices the
  // replacement container once the sidebar reappears.
  ensureTabStripObserverAttached() {
    const containerEl = this.getTabStripContainer();
    if (containerEl && containerEl !== this._observedTabStripContainerEl) {
      this.watchTabStrip();
    }
  }

  // -------------------------------------------------------------
  // Signal collection.
  // -------------------------------------------------------------

  handleVaultEvent(file) {
    if (!file || typeof file.extension !== 'string') return;
    if (file.extension.toLowerCase() !== 'md') return;

    const now = Date.now();
    // Second layer against the initial-indexing flood (see onLayoutReady
    // in onload()): anything arriving within VAULT_WARMUP_MS of handler
    // registration is treated as indexing noise, not a real write.
    if (isWithinVaultWarmup(now, this._vaultHandlersRegisteredMs)) return;

    // Exclude the file currently open in the active editor so the user's
    // own typing does not light the orb.
    const activeFile = this.app.workspace.getActiveFile?.();
    if (activeFile && file.path === activeFile.path) return;

    this._signals.lastVaultWriteMs = now;
    this._lastTouchedFile = file.name || file.basename || null;
    this.refreshUI();
  }

  async pollAutomationFiles() {
    // stop-state.json: freshest of file mtime and any entry's lastFiredMs.
    try {
      const stat = await fs.promises.stat(STOP_STATE_PATH);
      let freshest = stat.mtimeMs;
      try {
        const raw = await fs.promises.readFile(STOP_STATE_PATH, 'utf8');
        const data = JSON.parse(raw);
        if (data && typeof data === 'object') {
          for (const key of Object.keys(data)) {
            const entry = data[key];
            if (entry && typeof entry.lastFiredMs === 'number' && entry.lastFiredMs > freshest) {
              freshest = entry.lastFiredMs;
            }
          }
        }
      } catch (_) {
        // Missing/unparseable content is fine — mtime alone still stands.
      }
      this._signals.stopStateMs = freshest;
    } catch (_) {
      // Missing file is normal, not an error to surface.
      this._signals.stopStateMs = null;
    }

    // queue.jsonl / queue.batch.jsonl — during a drain the live file is
    // renamed to queue.batch.jsonl, so stat both and take the newer.
    let queueMtime = null;
    try {
      const stat = await fs.promises.stat(QUEUE_PATH);
      queueMtime = stat.mtimeMs;
    } catch (_) {
      /* missing is normal */
    }
    try {
      const stat = await fs.promises.stat(QUEUE_BATCH_PATH);
      queueMtime = queueMtime === null ? stat.mtimeMs : Math.max(queueMtime, stat.mtimeMs);
    } catch (_) {
      /* missing is normal */
    }
    this._signals.queueMs = queueMtime;

    // .drain.lock — opened FileShare::None by the drainer. A missing file
    // or a successful read means free. Only the specific Windows
    // sharing-violation signature (ERROR_SHARING_VIOLATION -> libuv EBUSY)
    // means genuinely HELD. Any other error (permissions, transient I/O
    // fault, etc.) is unknown, not held — a persistent non-lock error must
    // not pin the orb to "active" forever. computeState() treats
    // drainLockHeld === null the same as false (via `!!s.drainLockHeld`).
    try {
      const handle = await fs.promises.open(DRAIN_LOCK_PATH, 'r');
      await handle.close();
      this._signals.drainLockHeld = false;
    } catch (err) {
      if (err && err.code === 'ENOENT') {
        this._signals.drainLockHeld = false;
      } else if (err && err.code === 'EBUSY') {
        this._signals.drainLockHeld = true;
      } else {
        this._signals.drainLockHeld = null;
      }
    }

    this.refreshUI();
  }

  pollProcesses() {
    exec('tasklist /fo csv /nh', { windowsHide: true, timeout: 10000 }, (err, stdout) => {
      if (err || typeof stdout !== 'string') {
        // Unknown, not false — never crash, never flip the signal on a
        // failed/timed-out tasklist invocation. Deliberately leave
        // agentProcessCheckedMs untouched: computeState() uses its
        // staleness to stop trusting agentProcessAlive if refreshes keep
        // failing (e.g. the agent process exited and every poll after
        // that errors), instead of pinning the last-seen value forever.
        return;
      }
      const lower = stdout.toLowerCase();
      this._signals.agentProcessAlive = lower.includes('claude.exe') || lower.includes('codex.exe');
      this._signals.agentProcessCheckedMs = Date.now();
      this.refreshUI();
    });
  }

  // -------------------------------------------------------------
  // UI: orb state class + tooltip.
  // -------------------------------------------------------------

  describeSignal(now) {
    const s = this._signals;
    const vaultAgeMs = safeAgeMs(s.lastVaultWriteMs, now);
    const stopAgeMs = safeAgeMs(s.stopStateMs, now);
    const queueAgeMs = safeAgeMs(s.queueMs, now);

    if (vaultAgeMs < VAULT_WRITE_ACTIVE_MS) {
      return {
        label: this._lastTouchedFile ? `vault write (${this._lastTouchedFile})` : 'vault write',
        sinceMs: s.lastVaultWriteMs,
      };
    }
    if (stopAgeMs < AUTOMATION_FRESH_MS) {
      return { label: 'stop-state signal', sinceMs: s.stopStateMs };
    }
    if (queueAgeMs < AUTOMATION_FRESH_MS) {
      return { label: 'queue signal', sinceMs: s.queueMs };
    }
    if (s.drainLockHeld) {
      return { label: 'drain lock held', sinceMs: now };
    }
    if (s.agentProcessAlive && !isProcessSignalStale(s.agentProcessCheckedMs, now)) {
      return { label: 'agent process running', sinceMs: now };
    }
    return { label: 'no recent activity', sinceMs: s.lastVaultWriteMs };
  }

  refreshUI() {
    const now = Date.now();
    const state = computeState(this._signals, now);
    this._currentState = state;
    this.applyOrbState(state);
    this.updateTooltip(state, now);
  }

  applyOrbState(state) {
    if (!this._orbEl) return;
    this._orbEl.removeClass('is-idle');
    this._orbEl.removeClass('is-agent-present');
    this._orbEl.removeClass('is-active');
    this._orbEl.addClass(`is-${state}`);
  }

  updateTooltip(state, now) {
    if (!this._orbEl) return;
    const stateWords = { idle: 'Idle', 'agent-present': 'Agent present', active: 'Active' }[state] || state;
    const { label, sinceMs } = this.describeSignal(now);
    const rel = typeof sinceMs === 'number' ? formatRelative(now - sinceMs) : 'unknown';
    const text = `Agent Pulse: ${stateWords} — ${label} — ${rel}`;

    try {
      if (typeof setTooltip === 'function') {
        setTooltip(this._orbEl, text, { placement: 'right' });
        return;
      }
    } catch (_) {
      /* fall through to aria-label */
    }
    try {
      this._orbEl.setAttribute('aria-label', text);
    } catch (_) {
      /* nothing more we can do */
    }
  }
}

module.exports = AgentPulsePlugin;
module.exports.computeState = computeState;
module.exports.formatRelative = formatRelative;
module.exports.isWithinVaultWarmup = isWithinVaultWarmup;
module.exports.VAULT_WARMUP_MS = VAULT_WARMUP_MS;
