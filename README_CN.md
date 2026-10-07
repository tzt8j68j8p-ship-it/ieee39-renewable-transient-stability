# IEEE39 新能源暂态稳定与 CCT 自动化工具

[English](README.md)

基于 Python / ANDES 2.0.0，对 IEEE39 进行三相母线故障仿真、批量暂态响应分析和自动临界清除时间区间搜索，并比较四个新能源替代场景。项目保留验证边界、数值失败状态和模型哈希，提供独立运行入口。

<img src="docs/assets/renewable_cct_heatmap.png" alt="四个新能源场景与五个故障位置的CCT比较" width="860">

## 核心能力与结果

- 独立加载模型，自动执行 PFlow、初始化、TDS 与故障清除。
- 使用 setup 后 `GENROU.M.v` 计算 COI、相对功角和同时刻最大功角分离。
- 复用整数网格二分搜索及有界 bracket discovery。
- 分别记录运行状态与 STABLE / UNSTABLE / NON_CONVERGENT。
- 官方基线15母线：13个已解析、1个>500 ms下界、1个数值未解析。
- 新能源4场景×5故障位置：10个已解析、3个>500 ms下界、7个数值未解析；99项纯测试通过。

所有已解析区间宽度为 **7.8125 ms**，清除时间网格为1/128 s。estimate是验证区间中点，不能解释为超过仿真分辨率的精确物理CCT。未解析estimate保持null。

## 新能源主场景

| 场景 | 替代母线 | 实际有功占比 | SG / RenGen |
|---|---|---:|---:|
| S0 | 无，适配SG基线 | 0% | 10 / 0 |
| S1 | 37 | 8.845% | 9 / 1 |
| S2 | 37、38 | 22.440% | 8 / 2 |
| S3 | 37、38、32 | 33.087% | 7 / 3 |

模型采用REGCP1 + PLL2 + REECB1，保留原发电计划。主场景保留Bus39外部大系统等值机和Slack Bus31；Bus39替代场景仅作独立stress档案，不进入主矩阵。

结果具有故障位置与场景依赖性。Bus23已解析中点非递减；其他位置有未解析或下界结果，不能推断“新能源占比越高，稳定性必然越低”。替代位置、SG集合、惯量和GFL动态同时改变，不能只归因于有功占比。

## 快速运行

在项目根目录使用Python 3.13。Windows示例：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python run_fault.py --bus 16 --clear-time 0.125
.venv\Scripts\python run_cct.py --bus 16 --tc-max 0.1953125
```

已有批量入口为 `run_batch.py` 和 `run_scenario_comparison.py`，参数见英文首页。输出目录须为空；纯测试不启动TDS。查看已有结果无需重新仿真。

## 判据与数值失败

故障在1.0 s投入，`xf=1e-4 pu`，清除后保留网络，观察至8.0 s。COI仅使用当前场景剩余SG的系统基准M；同时刻功角分离>=180°作为筛选证据。

**这是剩余同步机转子角子系统判据，不能充分证明converter内部稳定。** PLL只是诊断，不加入COI或新增稳定阈值。TDS失败不自动等同物理失稳；可信越界先于异常时可保留UNSTABLE及失败信息，否则归为NON_CONVERGENT。搜索遇数值/质量失败立即停止，不移动边界，不绕过失败点。

## 资料与范围

[方法](docs/methodology.md) · [完整结果与三张核心图](docs/results.md) · [局限](docs/limitations.md) · [模型来源](docs/model_provenance.md) · [发布核验](docs/github_release_checklist.md)

验证环境为Python 3.13.15 / ANDES 2.0.0。模型、精简汇总和图片均有SHA256记录；原始大量轨迹、日志和内部逐日材料仅留本地，不提交Git。结果限于IEEE39/适配系统、通用GFL模型、8 s观察窗和有界搜索。

许可证：GPL-3.0-or-later，第三方归属见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
