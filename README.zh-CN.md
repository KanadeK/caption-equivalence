# caption-equivalence 中文说明

检查 SRT/WebVTT 转换后，在每个时间区间内显示的规范化字幕文本是否一致。
能发现丢字、额外字幕、重叠重复及时间改变；同一文本拆成相邻多段不会误报。

按 [英文 README](README.md) 克隆仓库并建立、激活 Python 3.11+ 虚拟环境后：

```sh
python -m pip install .
caption-equivalence examples/reference.srt examples/resegmented.vtt --json
# 预期退出 0：虽然字幕段数不同，但文本时间状态等价。
caption-equivalence examples/reference.srt examples/missing-tail.vtt --json
# 预期退出 1：丢失 1,000 毫秒字幕。
```

比较使用 `[开始, 结束)` 区间内的文本多重集合，保留重叠重复的次数。
规范化折叠空白、解码合法字符引用，并移除无属性且平衡的小写 b/i/u 样式标签。
不忽略大小写、标点或 Unicode 组合形式差异。不自动对齐时间，也不评价翻译语义。

退出码 0 表示等价或在明确设置的 `--max-different-ms` 预算内，1 表示超预算，
2 表示无效、不支持或超限输入。非零但被预算接受时标记为 `within_budget`，
不会宣称严格等价。空基准默认拒绝；有效的空候选仍会被检测出字幕损失。

仅支持文档声明的 UTF-8 SRT/WebVTT 子集。样式区块、区域、定位设置、声部标签、
卡拉 OK 内联时间和 ASS 指令会明确报错，而不是静默忽略。默认每文件 16 MiB、
50,000 段，最大同时活动 256 段。报告不含字幕正文与输入路径，但仍含时间、行号和哈希。

无运行时第三方依赖、联网或遥测。卸载用 `python -m pip uninstall caption-equivalence`，
再删除专用虚拟环境即可。完整限制、实际验证记录和测试命令见英文说明。
