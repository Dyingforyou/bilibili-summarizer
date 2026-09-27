"""视频总结助手 - 两阶段、类型自适应的 LLM 总结。"""
import json
import re
import time

import requests

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from provenance import build_source_chunks, extract_provenance, format_chunked_source


ANALYSIS_PROMPT = """你是视频内容分析编辑。请先分析转录稿，不要直接写成最终文章。

只输出合法 JSON，结构如下：
{
  "content_type": "investment|technical_learning|knowledge|interview|news_commentary|general|mixed",
  "one_sentence_thesis": "视频真正的中心命题",
  "topic_sections": [
    {
      "title": "主题模块",
      "main_point": "核心判断或知识",
      "reasoning": ["原文中的依据、因果链或推导"],
      "facts_and_numbers": ["原文明确出现的数据、时间、价格、名称"],
      "examples": ["原文案例"],
      "conditions_and_risks": ["适用条件、限制、反例、风险"]
    }
  ],
  "methods_or_steps": ["原文给出的方法、步骤或执行规则"],
  "key_terms": [{"term": "术语", "meaning": "结合上下文的解释"}],
  "speaker_conclusions": ["讲述者明确表达的结论"],
  "investment_scope": {
    "is_investment_related": false,
    "markets": [],
    "assets_or_sectors": [],
    "entry_conditions": [],
    "exit_conditions": [],
    "position_rules": [],
    "risk_controls": []
  }
}

分析规则：
1. 覆盖完整转录稿，不要只关注开头或标题；合并重复口语，但保留不同主题。
2. 严格区分“原文事实”“讲述者观点”“你的归纳”，不得补充外部知识或猜测缺失数据。
3. 数字、日期、点位、价格、比例和专有名词必须与原文一致；听写含糊时标注“转录可能有误”，不要擅自纠正。
4. 识别标题党、课程推广、闲聊等次要内容，降低权重但不要把重要限制条件删掉。
5. 投资内容要提取判断成立的前提、买卖条件、仓位、止损和风险；原文没说的字段保持空数组。
6. 技术学习或知识类内容要提取概念之间的关系、操作步骤、案例和常见误区。
"""


FINAL_PROMPT = """你是资深中文内容编辑。请根据“视频转录稿”和“证据化分析”写一份独立可读、信息密度高的中文总结。

通用要求：
1. 标题要准确概括核心议题，不夸张、不照抄视频标题。
2. 开头用一段“内容概览”说明视频讨论什么、核心结论是什么、采用了什么论证路径。
3. 正文按内容本身拆成 3～8 个有意义的主题章节。每章先给结论，再说明依据、因果、例子、数据、条件和限制；不要机械套用固定模板。
4. 重要数字、日期、点位、价格、比例、人物和标的要尽量保留，但只能使用转录稿明确出现的信息。
5. 明确使用“讲述者认为/视频观点是”等措辞标识主观判断，不把观点伪装成已证实事实。
6. 删除口头禅、重复、寒暄和低信息量推广；若课程或产品推广影响理解，可在末尾用一句话说明。
7. 不引用外部知识，不替含糊转录纠错，不捏造仓位、止损位、估值、时间窗口或操作结论。证据化分析若与转录稿冲突，以转录稿为准。
8. 避免空泛表述。篇幅随内容复杂度调整：简单视频可以短，长且多主题的视频应充分展开。
9. 输出前逐项核对所有数字的“对象—数值—单位—条件”，尤其不能把大盘与个股、买入与卖出、上涨与下跌的标准互换。
10. 转录稿已被切成 [S0001] 形式的证据片段。每个包含事实、观点、数字或结论的正文段落/列表项末尾，必须添加最相关的原文引用，格式严格为【原文:S0001】或【原文:S0001,S0002】。只能引用实际提供的编号；引用必须直接支持该段内容。标题无需引用。

类型自适应：
- 技术学习/知识类：重点写清“概念是什么—为什么—怎么做—案例—易错点/边界”，必要时给学习清单。
- 访谈/观点类：区分不同问题、观点、论据和分歧，不把主持人与嘉宾观点混为一谈。
- 新闻评论类：区分事件事实、影响链条和讲述者判断。
- 投资或混合投资类：正文应覆盖市场环境、逻辑链、具体方向/标的、估值或价格条件、交易纪律及主要风险。

投资类附加要求：
如果内容与投资相关，最后增加“## 视频中的操作条件与局限”章节：
- 只整理讲述者明确说出的条件、动作和风险；逐条引用支持它的原文片段。
- 原文未给出入场、退出、止损、仓位、期限等规则时，明确写“视频未给出”，不得补充通用投资常识或自行设计策略。尤其不得凭“行情可能上涨”推导出“分批建仓”，也不得凭“存在回撤风险”推导出“设置止损线”。
- 讲述者的个人仓位、历史交易和会员宣传只可作为其自述，不转写成对观众的操作建议。
- 严格区分“讲述者判断”和“已经证实的事实”；其未来走势预测不能写成确定结果。
- 每一个列表项末尾必须有直接支持的原文引用；找不到引用的项目应删除。没有明确可执行规则时，本节可以只写“视频未给出具体买卖、仓位或止损规则”。
- 结尾注明“以上为对视频观点的整理，不构成个性化投资建议”。

非投资内容不要硬加投资建议。
使用 Markdown 输出，不要输出分析过程或 JSON。
"""

LONG_MAP_PROMPT = """你负责整理长视频的其中一段转录稿。按顺序提取本段的主题、论点、依据、数据、例子、限制和重要原话。每个事实或观点都标注原文编号，格式【原文:S0001】。只引用输入中真实存在的编号；不要补充外部知识。尽量保留不同话题及关键数字，不要直接写整部视频的最终总结。输出结构清晰的中文笔记。"""

LONG_REDUCE_PROMPT = """将以下连续几段视频笔记压缩为一份可用于最终总结的证据笔记。保留每段独有的主题、具体数字、条件、反例和原文编号；只合并重复内容。每条事实或观点继续带原有【原文:S0001】格式引用，不得发明或改写编号，不得加入外部信息。"""

LONG_FINAL_PROMPT = FINAL_PROMPT.replace(
    "请根据“视频转录稿”和“证据化分析”写一份",
    "请根据覆盖完整视频的分段证据笔记写一份",
).replace(
    "证据化分析若与转录稿冲突，以转录稿为准。",
    "证据笔记有疑义时写明不确定，不自行补全。",
).replace(
    "转录稿已被切成 [S0001] 形式的证据片段。",
    "证据笔记保留了 [S0001] 形式的原文编号。",
)


def _chat(messages: list[dict], max_tokens: int, temperature: float = 0.2) -> str:
    if not LLM_API_KEY:
        raise RuntimeError("未配置 LLM_API_KEY，请复制 .env.example 为 .env 后填写")
    url = f"{LLM_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    last_error = None
    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=180)
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
            last_error = RuntimeError(
                f"LLM 请求失败 [{resp.status_code}]: {resp.text[:300]}"
            )
            # 参数、鉴权等 4xx 错误重试没有意义；限流除外。
            if resp.status_code < 500 and resp.status_code != 429:
                raise last_error
        except requests.RequestException as exc:
            last_error = exc
        if attempt < 2:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"LLM 请求连续失败: {last_error}")


def _clean_json_block(value: str) -> str:
    """移除模型偶尔添加的 Markdown JSON 围栏。"""
    value = value.strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)
    return value.strip()


def _group_by_size(items: list[str], max_chars: int) -> list[list[str]]:
    """保持时间顺序，将证据片段或笔记装入有限大小的请求。"""
    groups = []
    current = []
    current_size = 0
    for item in items:
        if current and current_size + len(item) + 2 > max_chars:
            groups.append(current)
            current = []
            current_size = 0
        current.append(item)
        current_size += len(item) + 2
    if current:
        groups.append(current)
    return groups


def _summarize_long(chunks: list[dict], title: str) -> str:
    source_items = [f"[{item['id']}] {item['text']}" for item in chunks]
    notes = []
    for group in _group_by_size(source_items, 14000):
        notes.append(_chat([
            {"role": "system", "content": LONG_MAP_PROMPT},
            {"role": "user", "content": "\n\n".join(group)},
        ], max_tokens=3000, temperature=0.1))

    # 特别长的视频会产生大量分段笔记；逐层压缩以控制最终请求大小。
    while sum(map(len, notes)) > 24000:
        new_notes = []
        for group in _group_by_size(notes, 16000):
            new_notes.append(_chat([
                {"role": "system", "content": LONG_REDUCE_PROMPT},
                {"role": "user", "content": "\n\n".join(group)},
            ], max_tokens=3000, temperature=0.1))
        if sum(map(len, new_notes)) >= sum(map(len, notes)):
            raise RuntimeError("长视频笔记无法压缩到模型输入范围，请更换更大上下文的模型")
        notes = new_notes

    return _chat([
        {"role": "system", "content": LONG_FINAL_PROMPT},
        {"role": "user", "content": f"视频标题：{title or '未提供'}\n\n按时间顺序的分段证据笔记：\n" + "\n\n".join(notes)},
    ], max_tokens=7000, temperature=0.2)


def summarize_text(transcript: str, title: str = "") -> tuple[str, str]:
    """先提取证据化提纲，再生成类型自适应的完整总结。"""
    chunks = build_source_chunks(transcript)
    if len(transcript) > 24000:
        summary = _summarize_long(chunks, title)
        return summary, extract_provenance(summary, chunks)

    chunked_transcript = format_chunked_source(chunks)
    source = f"视频标题：{title or '未提供'}\n\n视频转录稿：\n{chunked_transcript}"
    analysis_raw = _chat([
        {"role": "system", "content": ANALYSIS_PROMPT},
        {"role": "user", "content": source},
    ], max_tokens=5000, temperature=0.1)

    # 解析成功时重新序列化，减少围栏和无关文字；解析失败仍把原始提纲交给终稿模型。
    try:
        analysis = json.dumps(
            json.loads(_clean_json_block(analysis_raw)), ensure_ascii=False, indent=2
        )
    except (json.JSONDecodeError, TypeError):
        analysis = analysis_raw

    if len(transcript) >= 25000:
        length_hint = "这是一份长且多主题的转录稿，终稿建议约3500～6000个中文字符，确保不同主题均有充分展开。"
    elif len(transcript) >= 8000:
        length_hint = "这是一份中长转录稿，终稿建议约2200～4000个中文字符，兼顾覆盖度与可读性。"
    else:
        length_hint = "按实际信息量决定篇幅；内容简单时保持精炼，不要为凑长度重复扩写。"

    final_input = (
        f"{source}\n\n"
        "证据化分析（只作为提纲，所有细节仍须回查转录稿）：\n"
        f"{analysis}\n\n篇幅提示：{length_hint}"
    )
    summary = _chat([
        {"role": "system", "content": FINAL_PROMPT},
        {"role": "user", "content": final_input},
    ], max_tokens=7000, temperature=0.2)
    return summary, extract_provenance(summary, chunks)
