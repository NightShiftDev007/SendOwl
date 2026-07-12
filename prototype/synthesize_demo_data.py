#!/usr/bin/env python3
"""生成离线合成模拟数据，使对比页在无 Zep/真模拟时也能演示。

设计意图：三方案差异符合直觉假设——
- A 强硬：传播更快、负面更高、级联更深
- B 柔性：传播中等、负面较低、讨论更偏执行细节
- Baseline：传播最弱、观点分散
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs" / "synthetic"
SCENARIOS = json.loads((ROOT / "scenarios.json").read_text(encoding="utf-8"))

AGENTS = [
    {"id": 0, "name": "丰台交通支队", "role": "official", "stance_prior": "supportive"},
    {"id": 1, "name": "周明远", "role": "official", "stance_prior": "supportive"},
    {"id": 2, "name": "陈大伟", "role": "rider_leader", "stance_prior": "opposing"},
    {"id": 3, "name": "阿杰", "role": "rider", "stance_prior": "opposing"},
    {"id": 4, "name": "小雨", "role": "rider", "stance_prior": "opposing"},
    {"id": 5, "name": "赵婷", "role": "platform", "stance_prior": "neutral"},
    {"id": 6, "name": "王建国", "role": "commuter", "stance_prior": "supportive"},
    {"id": 7, "name": "刘敏", "role": "commuter", "stance_prior": "neutral"},
    {"id": 8, "name": "张丽", "role": "parent", "stance_prior": "supportive"},
    {"id": 9, "name": "老周", "role": "elder", "stance_prior": "opposing"},
    {"id": 10, "name": "孙姐", "role": "merchant", "stance_prior": "opposing"},
    {"id": 11, "name": "阿凯", "role": "kol", "stance_prior": "neutral"},
    {"id": 12, "name": "李楠", "role": "reporter", "stance_prior": "neutral"},
    {"id": 13, "name": "林晓薇", "role": "expert", "stance_prior": "neutral"},
]

TEMPLATES = {
    "supportive": [
        "支持限行，主干道安全必须优先。",
        "电动车抢道太危险了，该管管了。",
        "学校门口秩序乱，赞成整治。",
        "执法到位才能保护行人。",
    ],
    "opposing": [
        "没过渡期就是砸饭碗，反对一刀切。",
        "罚款太重了，骑手一天才赚多少？",
        "先修非机动车道再限行。",
        "商户客流会掉，政策太急。",
        "通行证不好办等于没有。",
    ],
    "neutral": [
        "能不能先试点看看效果？",
        "关键看配套措施是否到位。",
        "建议官方多做答疑，别只发公告。",
        "需要更多数据再下结论。",
        "换购补贴细节还不清楚。",
    ],
}


def _scenario_params(scenario_id: str) -> Dict[str, Any]:
    # base_* 是场景级立场先验（在 agent prior 之上叠加），用于保证验收方向稳定
    if scenario_id == "A_hard":
        return {
            "rounds": 25,
            "posts_per_round": (3, 8),
            "repost_rate": 0.45,
            "comment_rate": 0.55,
            "base_support": 0.22,
            "base_oppose": 0.48,
            "base_neutral": 0.30,
            "seed_posts": 2,
            "cascade_bias": 1.4,
            "rider_activation": 1.6,
        }
    if scenario_id == "B_soft":
        return {
            "rounds": 25,
            "posts_per_round": (2, 6),
            "repost_rate": 0.32,
            "comment_rate": 0.48,
            "base_support": 0.34,
            "base_oppose": 0.28,
            "base_neutral": 0.38,
            "seed_posts": 2,
            "cascade_bias": 1.0,
            "rider_activation": 1.0,
        }
    return {
        "rounds": 25,
        "posts_per_round": (1, 3),
        "repost_rate": 0.18,
        "comment_rate": 0.30,
        "base_support": 0.28,
        "base_oppose": 0.30,
        "base_neutral": 0.42,
        "seed_posts": 1,
        "cascade_bias": 0.6,
        "rider_activation": 0.8,
    }


def _sample_stance(agent: Dict[str, Any], params: Dict[str, Any], rng: random.Random) -> str:
    """场景基线 + agent prior 混合，确保强硬方案反对显著更高。"""
    weights = {
        "supportive": float(params["base_support"]),
        "opposing": float(params["base_oppose"]),
        "neutral": float(params["base_neutral"]),
    }
    prior = agent["stance_prior"]
    if prior == "supportive":
        weights["supportive"] += 0.25
        weights["opposing"] *= 0.55
    elif prior == "opposing":
        weights["opposing"] += 0.30
        weights["supportive"] *= 0.55
    else:
        weights["neutral"] += 0.15

    # 强硬方案下骑手/商户更活跃地表达反对
    if agent["role"] in ("rider", "rider_leader", "merchant"):
        weights["opposing"] *= float(params.get("rider_activation", 1.0))

    s = sum(weights.values()) or 1.0
    keys = list(weights)
    probs = [weights[k] / s for k in keys]
    return rng.choices(keys, weights=probs, k=1)[0]


def generate_scenario(scenario: Dict[str, Any]) -> Dict[str, Any]:
    rng = random.Random(hash(scenario["id"]) & 0xFFFFFFFF)
    params = _scenario_params(scenario["id"])
    start = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
    actions: List[Dict[str, Any]] = []
    posts: List[Dict[str, Any]] = []
    action_id = 0
    post_id = 0

    # seed posts from scenario
    for i, seed in enumerate(scenario["initial_posts"]):
        agent = AGENTS[0] if seed.get("poster_hint") == "official" else AGENTS[7]
        post_id += 1
        ts = start + timedelta(minutes=i)
        post = {
            "post_id": post_id,
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "content": seed["content"],
            "round": 0,
            "timestamp": ts.isoformat(),
            "stance": "supportive" if seed.get("poster_hint") == "official" else "neutral",
            "depth": 0,
            "parent_post_id": None,
        }
        posts.append(post)
        action_id += 1
        actions.append(
            {
                "action_id": action_id,
                "round": 0,
                "timestamp": ts.isoformat(),
                "agent_id": agent["id"],
                "agent_name": agent["name"],
                "action_type": "CREATE_POST",
                "content": seed["content"],
                "post_id": post_id,
                "stance": post["stance"],
            }
        )

    for round_num in range(1, params["rounds"] + 1):
        n = rng.randint(*params["posts_per_round"])
        for _ in range(n):
            agent = rng.choice(AGENTS[1:])  # skip repeating official too often
            stance = _sample_stance(agent, params, rng)
            content = rng.choice(TEMPLATES[stance])
            ts = start + timedelta(hours=round_num, minutes=rng.randint(0, 50))

            # decide create / comment / repost
            roll = rng.random()
            parent = None
            depth = 0
            action_type = "CREATE_POST"
            if posts and roll < params["repost_rate"] * params["cascade_bias"]:
                parent = rng.choice(posts[-max(3, len(posts) // 3) :])
                action_type = "REPOST"
                depth = int(parent.get("depth", 0)) + 1
                content = f"转发：{parent['content'][:40]}… {content}"
            elif posts and roll < params["repost_rate"] + params["comment_rate"]:
                parent = rng.choice(posts[-max(5, len(posts) // 2) :])
                action_type = "CREATE_COMMENT"
                depth = int(parent.get("depth", 0)) + 1
                content = f"回复 @{parent['agent_name']}：{content}"

            post_id += 1
            post = {
                "post_id": post_id,
                "agent_id": agent["id"],
                "agent_name": agent["name"],
                "content": content,
                "round": round_num,
                "timestamp": ts.isoformat(),
                "stance": stance,
                "depth": depth,
                "parent_post_id": parent["post_id"] if parent else None,
            }
            posts.append(post)
            action_id += 1
            actions.append(
                {
                    "action_id": action_id,
                    "round": round_num,
                    "timestamp": ts.isoformat(),
                    "agent_id": agent["id"],
                    "agent_name": agent["name"],
                    "action_type": action_type,
                    "content": content,
                    "post_id": post_id,
                    "parent_post_id": post["parent_post_id"],
                    "stance": stance,
                }
            )

            # likes
            if rng.random() < 0.4:
                liker = rng.choice(AGENTS)
                action_id += 1
                actions.append(
                    {
                        "action_id": action_id,
                        "round": round_num,
                        "timestamp": (ts + timedelta(minutes=1)).isoformat(),
                        "agent_id": liker["id"],
                        "agent_name": liker["name"],
                        "action_type": "LIKE_POST",
                        "post_id": post_id,
                    }
                )

    # interviews
    interviews = []
    for agent in [AGENTS[2], AGENTS[6], AGENTS[10]]:
        if agent["stance_prior"] == "opposing":
            ans = (
                f"我是{agent['name']}。反对强硬一刀切，因为直接影响生计/客流；"
                "如果有试点和补贴，可以谈。"
                if scenario["id"] != "B_soft"
                else f"我是{agent['name']}。柔性方案比强硬好，但仍担心通行证和补贴落地。"
            )
        else:
            ans = f"我是{agent['name']}。主干道安全问题确实严重，支持把秩序立起来，但也希望配套跟上。"
        interviews.append(
            {
                "agent_id": agent["id"],
                "agent_name": agent["name"],
                "question": "你为什么支持或反对这次限行政策发布方式？",
                "answer": ans,
            }
        )

    return {
        "scenario_id": scenario["id"],
        "scenario_name": scenario["name"],
        "hypothesis": scenario.get("hypothesis"),
        "agents": AGENTS,
        "actions": actions,
        "posts": posts,
        "interviews": interviews,
        "synthetic": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def generate_all() -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    index = []
    for scenario in SCENARIOS["scenarios"]:
        data = generate_scenario(scenario)
        out_dir = OUTPUTS / scenario["id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "bundle.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with (out_dir / "actions.jsonl").open("w", encoding="utf-8") as f:
            for a in data["actions"]:
                f.write(json.dumps(a, ensure_ascii=False) + "\n")
        (out_dir / "interviews.json").write_text(
            json.dumps(data["interviews"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        index.append(
            {
                "scenario_id": scenario["id"],
                "scenario_name": scenario["name"],
                "color": scenario.get("color"),
                "actions": len(data["actions"]),
                "posts": len(data["posts"]),
                "path": str(out_dir.relative_to(ROOT)),
            }
        )
        print(f"  synthesized {scenario['id']}: actions={len(data['actions'])} posts={len(data['posts'])}")
    (OUTPUTS / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    generate_all()
