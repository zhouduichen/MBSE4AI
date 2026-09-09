# AI4MBSE public-real-v1 prompts

这些 Prompt 是可重复的演示输入，不是历史飞机的官方设计数据。

## PROMPT-TACTICAL-ISR（主 Demo）

设计一型战术侦察固定翼无人机，最大起飞重量不超过700kg，任务载荷不少于150kg，翼展不超过12m，能够执行持续侦察；通信链路中断后应进入安全返航流程。

验证：1.1 constraints；1.2 lost-link scenario；2.1 similar retrieval；2.2 evaluation/Pareto。

## PROMPT-MALE-ISR

生成一型中空长航时侦察无人机概念方案，最大起飞重量约1200kg，任务载荷350kg以上，翼展15到17m，机身长度8到9m，巡航或任务飞行速度约35到45m/s，并支持超视距任务。

验证：1.1 ranges/units；2.1 retrieval/diversity；2.2 three disciplines。

## PROMPT-HIGH-PAYLOAD（边界 / trade-off）

设计一型最大起飞重量不超过1900kg、任务载荷不少于400kg、翼展约17m的长航时无人机总体概念方案，优先降低总质量并保持较好的气动效率。

验证：2.1 hard constraints；2.2 multi-objective Pareto。系统不得为了生成结果偷偷放宽 hard constraint。
