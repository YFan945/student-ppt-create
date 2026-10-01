# 学生Python并发课程中文资料研究验收
scenario: coursework
budget: standard
semantic_review_required: true
scope: B
C01 core/source: ThreadPoolExecutor使用线程池异步执行调用。
C02 core/source: Future.cancel不能取消已经运行或已经完成的调用。
C03 supporting/source: Executor.map 的 buffersize 参数是 Python 3.14 新增的。
验收：每条有可读原文片段支持，优先中文官方文档 https://docs.python.org/zh-cn/3/library/concurrent.futures.html 。至少一次WebSearch定位中文来源并记录实际响应，索引失败可按已知URL直取。C03要明确版本限定，不把3.14新行为当成所有旧版行为。每拿到一条直接支持就保存并校验包，其余暂列unresolved。不要为普通单源论断寻找第二份出处，不生成PPTX。
