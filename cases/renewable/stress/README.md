# External-equivalent stress scenarios

Day3A 原 S2（Bus37 + Bus39）与 S3（Bus37 + Bus39 + Bus38）模型、结果完整保留在原位置。此目录的 manifest 通过相对路径引用原模型，明确标记为 external-equivalent stress scenarios，禁止纳入 Day3B 主 renewable-penetration heatmap。

Bus39 为 H=50 s、setup M=1199 的外部大系统等值机。对它的替换同时改变极大的同步惯量，属于单独压力场景，不能作为普通新能源渗透率阶梯。

主场景入口是 `../main/manifest.json`；总目录入口是 `../scenario_catalog.json`。原 `../manifest.json` 作为 Day3A 历史档案保留，不再作为主 heatmap 场景入口。没有复制或重新运行压力场景。
