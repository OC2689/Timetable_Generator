"""
CSP timetable solver (pure Python, no Flask dependency).

Model
-----
Variable : one weekly session (class, course, Lecture/Practical, duration).
Domain   : every (day, start_period, room_id) that satisfies the *unary* hard
           constraints (faculty available day, room capacity, lab/non-lab room,
           inside the day, practical does not cross the break).
Binary hard constraints (checked/propagated during search):
           - same class      -> no time overlap     (no student-group clash)
           - same faculty    -> no time overlap     (no teacher clash)
           - same room       -> no time overlap
           - faculty total periods <= max_periods
Soft constraints (minimised, never block a solution):
           - gaps / empty periods inside a class's day
           - consecutive "difficult" subjects (category Core)
           - same course twice on one day (poor spread)
           - faculty teaching more than MAX_FAC_PER_DAY periods in one day

Search
------
Recursive backtracking with
           - MRV (Minimum Remaining Values) variable ordering, ties broken by
             longer duration / busier faculty (degree-style heuristic)
           - forward checking (prune domains of unassigned variables)
           - constraint propagation (a variable whose domain shrinks to one
             value is assigned immediately and its pruning is propagated on)
           - value ordering by lowest soft-constraint cost (random tie-break)
"""
import random
import sys
import time

W_GAP = 2            # each empty period between a class's first and last period of a day
W_ADJ = 3            # two difficult sessions back-to-back (not across the break)
W_SAMEDAY = 2        # same course scheduled twice on the same day
W_FACLOAD = 2        # each faculty period above MAX_FAC_PER_DAY on one day
MAX_FAC_PER_DAY = 4
DIFFICULT_CATEGORIES = {"core"}


class Var:
    __slots__ = ("idx", "cls", "course", "kind", "dur", "fid", "difficult",
                 "domain", "rooms", "label")

    def __init__(self, idx, cls, course, kind, dur, fid, difficult, domain, label):
        self.idx, self.cls, self.course, self.kind = idx, cls, course, kind
        self.dur, self.fid, self.difficult = dur, fid, difficult
        self.domain = domain
        self.rooms = {w[2] for w in domain}
        self.label = label


class Problem:
    def __init__(self, variables, errors, fac_cap, break_after):
        self.vars = variables
        self.errors = errors          # sessions that can never be placed (empty initial domain)
        self.fac_cap = fac_cap
        self.break_after = break_after


def build_problem(classes, courses, faculty, rooms, working_days, periods_per_day, break_after):
    fac = {f["id"]: f for f in faculty}
    fac_cap = {f["id"]: int(f["max_periods"]) for f in faculty}
    errors, drafts = [], []
    for cl in classes:
        for co in courses:
            fid = co["faculty_id"]
            if not fid or fid not in fac:
                errors.append(f'{co["code"]}: assign a faculty member first.')
                continue
            allowed = {int(x) for x in (fac[fid]["available_days"] or "").split(",") if x.strip().isdigit()}
            specs = [("Lecture", int(co["lectures_per_week"]), 1),
                     ("Practical", int(co["practicals_per_week"]), max(1, int(co["practical_duration"])))]
            for kind, count, dur in specs:
                for _ in range(count):
                    elig = [r for r in rooms if r["capacity"] >= cl["students"] and
                            ((r["room_type"].lower() == "lab") == (kind == "Practical"))]
                    domain = []
                    for day in range(1, working_days + 1):
                        if allowed and day not in allowed:
                            continue
                        for start in range(1, periods_per_day - dur + 2):
                            if dur > 1 and break_after and start <= break_after < start + dur - 1:
                                continue          # never cross the break
                            for r in elig:
                                domain.append((day, start, r["id"]))
                    label = f'{co["code"]} {kind.lower()} for {cl["code"]}'
                    if not domain:
                        why = ("no lab with enough capacity" if kind == "Practical" and not elig else
                               "no classroom with enough capacity" if not elig else
                               "faculty unavailable / session does not fit the day")
                        errors.append(f'Could not schedule {label} ({dur} period(s)): {why}.')
                        continue
                    drafts.append((cl, co, kind, dur, fid, domain, label))
    # static order used by the non-MRV baselines: longest sessions, then lab sessions first
    drafts.sort(key=lambda d: (-d[3], len(d[5]), d[1]["code"], d[0]["code"]))
    # Workload pre-check: a faculty member whose demand exceeds max_periods makes the
    # problem infeasible. Report it and lift that cap so the rest can still be solved.
    demand = {}
    for d in drafts:
        demand[d[4]] = demand.get(d[4], 0) + d[3]
    for fid, need in demand.items():
        if need > fac_cap[fid]:
            errors.append(f'Faculty {fac[fid]["code"]} is overloaded: needs {need} periods/week but max is '
                          f'{fac_cap[fid]}. Raise max periods, add faculty, or reduce sessions.')
            fac_cap[fid] = need
    variables = []
    for i, (cl, co, kind, dur, fid, domain, label) in enumerate(drafts):
        diff = (co["category"] or "").strip().lower() in DIFFICULT_CATEGORIES
        variables.append(Var(i, cl["id"], co["id"], kind, dur, fid, diff, domain, label))
    return Problem(variables, errors, fac_cap, break_after)


class Solver:
    def __init__(self, problem, use_mrv=True, use_fc=True, use_prop=True, use_soft=True,
                 seed=0, max_nodes=20000, time_limit=5.0):
        self.p, self.vars = problem, problem.vars
        self.n = len(self.vars)
        self.use_mrv, self.use_fc = use_mrv, use_fc
        self.use_prop = use_prop and use_fc
        self.use_soft = use_soft
        self.rng = random.Random(seed)
        self.max_nodes, self.time_limit = max_nodes, time_limit
        self.dom = [set(v.domain) for v in self.vars]
        self.assigned = [None] * self.n
        self.n_assigned = 0
        self.occ_cls, self.occ_fac, self.occ_room = set(), set(), set()
        self.load = {}
        self.cd_periods, self.cd_diff, self.fd_load, self.cc_days = {}, {}, {}, {}
        self.trail = []
        self.nodes = self.backtracks = 0
        self.timed_out = False
        self.best_count, self.best_snapshot = -1, {}
        self.strict = True            # False => best-effort mode: wipe-outs mean 'leave unscheduled'
        self.fac_demand = {}
        for v in self.vars:
            self.fac_demand[v.fid] = self.fac_demand.get(v.fid, 0) + v.dur

    # ---------- state changes (all reversible through the trail) ----------
    def _consistent(self, i, val):
        v, (d, s, r) = self.vars[i], val
        if self.load.get(v.fid, 0) + v.dur > self.p.fac_cap.get(v.fid, 10 ** 9):
            return False
        for p in range(s, s + v.dur):
            if ((v.cls, d, p) in self.occ_cls or (v.fid, d, p) in self.occ_fac
                    or (r, d, p) in self.occ_room):
                return False
        return True

    def _do_assign(self, i, val):
        v, (d, s, r) = self.vars[i], val
        cells = range(s, s + v.dur)
        for p in cells:
            self.occ_cls.add((v.cls, d, p)); self.occ_fac.add((v.fid, d, p)); self.occ_room.add((r, d, p))
        self.load[v.fid] = self.load.get(v.fid, 0) + v.dur
        self.cd_periods.setdefault((v.cls, d), set()).update(cells)
        if v.difficult:
            self.cd_diff.setdefault((v.cls, d), set()).update(cells)
        self.fd_load[(v.fid, d)] = self.fd_load.get((v.fid, d), 0) + v.dur
        key = (v.cls, v.course)
        self.cc_days.setdefault(key, {})
        self.cc_days[key][d] = self.cc_days[key].get(d, 0) + 1
        self.assigned[i] = val
        self.n_assigned += 1
        self.trail.append(("a", i, val))

    def _undo(self, mark):
        while len(self.trail) > mark:
            op = self.trail.pop()
            if op[0] == "d":
                self.dom[op[1]] |= op[2]
                continue
            self._remove(op[1])

    def _remove(self, i):
        d, s, r = self.assigned[i]
        v = self.vars[i]
        for p in range(s, s + v.dur):
            self.occ_cls.discard((v.cls, d, p)); self.occ_fac.discard((v.fid, d, p))
            self.occ_room.discard((r, d, p))
            self.cd_periods[(v.cls, d)].discard(p)
            if v.difficult:
                self.cd_diff[(v.cls, d)].discard(p)
        self.load[v.fid] -= v.dur
        self.fd_load[(v.fid, d)] -= v.dur
        self.cc_days[(v.cls, v.course)][d] -= 1
        self.assigned[i] = None
        self.n_assigned -= 1

    def improve(self, assignment, time_limit=3.0, max_passes=30):
        """Local search on a feasible assignment: move one session at a time to the cheapest
        value that keeps every hard constraint satisfied. Never increases the soft penalty."""
        self.strict = False
        for i, val in assignment.items():
            self._do_assign(i, val)
        deadline = time.time() + time_limit
        order = list(assignment)
        for _ in range(max_passes):
            changed = False
            self.rng.shuffle(order)
            for i in order:
                if time.time() > deadline:
                    break
                cur = self.assigned[i]
                self._remove(i)
                best_val, best_cost = cur, None
                for w in self.vars[i].domain:
                    if self._consistent(i, w):
                        c = self._soft_cost(i, w)
                        if best_cost is None or c < best_cost - 1e-9 or (w == cur and abs(c - best_cost) < 1e-9):
                            best_val, best_cost = w, c
                self._do_assign(i, best_val)
                if best_val != cur:
                    changed = True
            self.trail.clear()
            if not changed or time.time() > deadline:
                break
        return {i: a for i, a in enumerate(self.assigned) if a is not None}

    def _prune_from(self, k, queue):
        """Forward checking from the newly assigned variable k. Returns False on a domain wipe-out."""
        vk = self.vars[k]
        d, s, r = self.assigned[k]
        e = s + vk.dur
        for j in range(self.n):
            if self.assigned[j] is not None:
                continue
            vj = self.vars[j]
            same_cls, same_fac = vj.cls == vk.cls, vj.fid == vk.fid
            if same_fac and self.load.get(vk.fid, 0) + vj.dur > self.p.fac_cap.get(vk.fid, 10 ** 9):
                if self.strict:
                    return False                   # faculty workload cap can no longer be met
                if self.dom[j]:
                    self.trail.append(("d", j, set(self.dom[j])))
                    self.dom[j] = set()
                continue
            if not (same_cls or same_fac) and r not in vj.rooms:
                continue
            dj = vj.dur
            removed = {w for w in self.dom[j]
                       if w[0] == d and w[1] < e and s < w[1] + dj and (same_cls or same_fac or w[2] == r)}
            if not removed:
                continue
            self.dom[j] -= removed
            self.trail.append(("d", j, removed))
            if not self.dom[j]:
                if self.strict:
                    return False
                continue
            if self.use_prop and self.strict and len(self.dom[j]) == 1:   # constraint propagation: forced value
                forced = next(iter(self.dom[j]))
                if not self._consistent(j, forced):
                    return False
                self._do_assign(j, forced)
                queue.append(j)
        return True

    def _assign(self, i, val):
        if not self._consistent(i, val):
            return False
        self._do_assign(i, val)
        if not self.use_fc:
            return True
        queue = [i]
        while queue:
            if not self._prune_from(queue.pop(), queue):
                return False
        return True

    # ---------- soft constraints ----------
    def _soft_cost(self, i, val):
        v, (d, s, r) = self.vars[i], val
        cells = set(range(s, s + v.dur))
        per = self.cd_periods.get((v.cls, d), set())

        def gaps(ps):
            return (max(ps) - min(ps) + 1 - len(ps)) if ps else 0
        cost = W_GAP * (gaps(per | cells) - gaps(per))
        if v.difficult:
            diff = self.cd_diff.get((v.cls, d), set())
            ba = self.p.break_after
            if (s - 1) in diff and (s - 1) != ba:
                cost += W_ADJ
            if (s + v.dur) in diff and (s + v.dur - 1) != ba:
                cost += W_ADJ
        cost += W_SAMEDAY * self.cc_days.get((v.cls, v.course), {}).get(d, 0)
        before = self.fd_load.get((v.fid, d), 0)
        cost += W_FACLOAD * (max(0, before + v.dur - MAX_FAC_PER_DAY) - max(0, before - MAX_FAC_PER_DAY))
        return cost

    # ---------- heuristics ----------
    def _live_domain(self, j):
        if self.use_fc:
            return self.dom[j]
        return [w for w in self.vars[j].domain if self._consistent(j, w)]

    def _select(self):
        if not self.use_mrv:                                   # static order baseline
            for j in range(self.n):
                if self.assigned[j] is None:
                    return j
        best, best_key = None, None
        for j in range(self.n):
            if self.assigned[j] is not None:
                continue
            v = self.vars[j]
            key = (len(self._live_domain(j)), -v.dur, -self.fac_demand[v.fid], self.rng.random())
            if best_key is None or key < best_key:
                best, best_key = j, key
        return best

    def _ordered_values(self, i):
        vals = list(self._live_domain(i))
        if self.use_soft:
            scored = [(self._soft_cost(i, w) + self.rng.random() * 0.5, w) for w in vals]
            scored.sort()
            return [w for _, w in scored]
        vals.sort()
        return vals

    # ---------- search ----------
    def _snapshot(self):
        self.best_count = self.n_assigned
        self.best_snapshot = {i: a for i, a in enumerate(self.assigned) if a is not None}

    def _search(self):
        if self.n_assigned == self.n:
            return True
        if self.nodes >= self.max_nodes or time.time() > self.deadline:
            self.timed_out = True
            return False
        self.nodes += 1
        i = self._select()
        for val in self._ordered_values(i):
            mark = len(self.trail)
            if self._assign(i, val):
                if self.n_assigned > self.best_count:
                    self._snapshot()
                if self._search():
                    return True
            self._undo(mark)
            if self.timed_out:
                return False
            self.backtracks += 1
        return False

    def solve_best_effort(self):
        """No backtracking: repeatedly place the most constrained placeable session (MRV) with its
        cheapest value; sessions whose domain is wiped out are reported as unscheduled."""
        t0 = time.time()
        self.strict = False
        deadline = t0 + self.time_limit
        while time.time() < deadline:
            cand = [j for j in range(self.n) if self.assigned[j] is None and self.dom[j]]
            if not cand:
                break
            j = min(cand, key=lambda x: (len(self.dom[x]), -self.vars[x].dur, self.rng.random()))
            placed = False
            for val in self._ordered_values(j):
                if self._consistent(j, val):
                    self._do_assign(j, val)
                    self._prune_from(j, [])
                    placed = True
                    break
            if not placed:
                self.dom[j] = set()
        assignment = {i: a for i, a in enumerate(self.assigned) if a is not None}
        return {"solved": len(assignment) == self.n, "assignment": assignment, "nodes": len(assignment),
                "backtracks": 0, "seconds": time.time() - t0, "timed_out": False}

    def solve(self):
        sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))
        t0 = time.time()
        self.deadline = t0 + self.time_limit
        solved = self._search()
        assignment = ({i: a for i, a in enumerate(self.assigned) if a is not None}
                      if solved else dict(self.best_snapshot))
        return {"solved": solved, "assignment": assignment, "nodes": self.nodes,
                "backtracks": self.backtracks, "seconds": time.time() - t0,
                "timed_out": self.timed_out}


# ---------- independent evaluation ----------
def hard_violations(problem, assignment):
    """Re-checks every hard constraint from scratch (does not trust the solver)."""
    bad, seen = 0, {}
    load = {}
    for i, (d, s, r) in assignment.items():
        v = problem.vars[i]
        load[v.fid] = load.get(v.fid, 0) + v.dur
        for p in range(s, s + v.dur):
            for key in (("c", v.cls, d, p), ("f", v.fid, d, p), ("r", r, d, p)):
                if key in seen:
                    bad += 1
                seen[key] = i
    for fid, total in load.items():
        if total > problem.fac_cap.get(fid, 10 ** 9):
            bad += 1
    return bad


def soft_penalty(problem, assignment):
    cd, diff, fd, cc = {}, {}, {}, {}
    for i, (d, s, r) in assignment.items():
        v = problem.vars[i]
        cd.setdefault((v.cls, d), set()).update(range(s, s + v.dur))
        if v.difficult:
            diff.setdefault((v.cls, d), []).append((s, s + v.dur - 1))
        fd[(v.fid, d)] = fd.get((v.fid, d), 0) + v.dur
        cc[(v.cls, v.course, d)] = cc.get((v.cls, v.course, d), 0) + 1
    gaps = sum(max(ps) - min(ps) + 1 - len(ps) for ps in cd.values())
    ba = problem.break_after
    adj = 0                                   # two *different* difficult sessions back-to-back, not across the break
    for blocks in diff.values():
        for (s1, e1) in blocks:
            for (s2, e2) in blocks:
                if s2 == e1 + 1 and e1 != ba:
                    adj += 1
    same = sum(n * (n - 1) // 2 for n in cc.values())
    over = sum(max(0, n - MAX_FAC_PER_DAY) for n in fd.values())
    total = W_GAP * gaps + W_ADJ * adj + W_SAMEDAY * same + W_FACLOAD * over
    return {"total": total, "empty_periods": gaps, "consecutive_difficult": adj,
            "same_course_same_day": same, "faculty_overload": over}


STRATEGIES = [
    ("Plain backtracking (static order)", dict(use_mrv=False, use_fc=False, use_prop=False, use_soft=False), [0], 1.5),
    ("Backtracking + forward checking", dict(use_mrv=False, use_fc=True, use_prop=False, use_soft=False), [0], 2.0),
    ("MRV + forward checking", dict(use_mrv=True, use_fc=True, use_prop=False, use_soft=False), [0, 1], 2.5),
    ("MRV + FC + propagation", dict(use_mrv=True, use_fc=True, use_prop=True, use_soft=False), [0, 1], 2.5),
    ("MRV + FC + prop + soft value ordering", dict(use_mrv=True, use_fc=True, use_prop=True, use_soft=True), [11, 22], 2.0),
]


def solve_and_compare(problem, strategies=STRATEGIES, max_nodes=20000):
    """Run every strategy; return (best_result, comparison_rows)."""
    total = len(problem.vars)
    rows, best = [], None
    for name, opts, seeds, limit in strategies:
        for seed in seeds:
            res = Solver(problem, seed=seed, max_nodes=max_nodes, time_limit=limit, **opts).solve()
            soft = soft_penalty(problem, res["assignment"])
            row = {"strategy": name, "seed": seed, "placed": len(res["assignment"]), "total": total,
                   "hard_violations": hard_violations(problem, res["assignment"]),
                   "soft": soft, "nodes": res["nodes"], "backtracks": res["backtracks"],
                   "seconds": round(res["seconds"], 3), "timed_out": res["timed_out"], "result": res}
            rows.append(row)
            key = (row["hard_violations"], total - row["placed"], soft["total"])
            if best is None or key < best[0]:
                best = (key, row)
    if best[1]["placed"] < total:          # no strategy found a complete timetable -> best-effort fallback
        for seed in (11, 22, 33):
            res = Solver(problem, use_mrv=True, use_fc=True, use_prop=False, use_soft=True,
                         seed=seed, time_limit=4.0).solve_best_effort()
            soft = soft_penalty(problem, res["assignment"])
            row = {"strategy": "MRV best-effort fallback (skip unplaceable)", "seed": seed,
                   "placed": len(res["assignment"]), "total": total,
                   "hard_violations": hard_violations(problem, res["assignment"]), "soft": soft,
                   "nodes": res["nodes"], "backtracks": 0, "seconds": round(res["seconds"], 3),
                   "timed_out": False, "result": res}
            rows.append(row)
            key = (row["hard_violations"], total - row["placed"], soft["total"])
            if key < best[0]:
                best = (key, row)
    # Final stage: soft-constraint local search on the best CSP result (hard constraints stay satisfied).
    base = best[1]
    imp = Solver(problem, use_mrv=True, use_fc=False, use_prop=False, use_soft=True, seed=99)
    t0 = time.time()
    better = imp.improve(base["result"]["assignment"], time_limit=3.0)
    res = {"solved": len(better) == total, "assignment": better, "nodes": base["nodes"],
           "backtracks": base["backtracks"], "seconds": time.time() - t0, "timed_out": False}
    soft = soft_penalty(problem, better)
    row = {"strategy": "Best CSP result + soft-constraint local search", "seed": 99, "placed": len(better),
           "total": total, "hard_violations": hard_violations(problem, better), "soft": soft,
           "nodes": base["nodes"], "backtracks": base["backtracks"], "seconds": round(res["seconds"], 3),
           "timed_out": False, "result": res}
    rows.append(row)
    key = (row["hard_violations"], total - row["placed"], soft["total"])
    if key <= best[0]:
        best = (key, row)
    return best[1], rows
