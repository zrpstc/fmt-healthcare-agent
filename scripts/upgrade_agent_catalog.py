"""Apply the reviewed main/subagent prompts without changing model settings."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from app.agent_prompts import (
    EVIDENCE_AGENT_ID, EVIDENCE_SYSTEM_PROMPT, MAIN_AGENT_ID,
    MAIN_SYSTEM_PROMPT, normalize_agents,
)
from wgs_fmt_platform.paths import runtime_path


def main() -> None:
    path = runtime_path("WGS_AGENT_CONFIG_DIR", "agent-config") / "agents.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    if not any(row.get("id") == EVIDENCE_AGENT_ID for row in rows):
        rows.append({"id": EVIDENCE_AGENT_ID, "name": "循证整理助手", "model": "",
                     "skill_ids": ["evidence-retrieval"], "enabled": True, "color": "coral"})
    rows = normalize_agents(rows)
    for row in rows:
        if row["id"] == MAIN_AGENT_ID:
            row.update(system_prompt=MAIN_SYSTEM_PROMPT, description="统一负责宏基因组与FMT样本分析、循证委派及结果交付。")
        elif row["id"] == EVIDENCE_AGENT_ID:
            row.update(system_prompt=EVIDENCE_SYSTEM_PROMPT, skill_ids=["evidence-retrieval"],
                       description="由FMT科研助手按需调用的只读循证检索与交叉核验 subagent。")
        row["updated_at"] = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    print('Agent catalog upgraded: one primary; evidence-curator is a read-only subagent.')


if __name__ == '__main__':
    main()
