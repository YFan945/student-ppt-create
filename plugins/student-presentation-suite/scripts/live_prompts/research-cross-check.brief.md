# 学生计算机课程研究验收
scenario: coursework
budget: standard
semantic_review_required: true
scope: B
C01 core/cross_check: 在默认启用GIL的CPython中，同一时刻通常只有一个线程执行Python字节码。
C02 supporting/source: 该限制不代表所有I/O操作都必须串行执行。
验收：C01需要两个独立机构的可读原文支持，不把不同Python文档当独立来源；明确默认GIL构建与free-threaded的区别，不能推广到所有Python实现。至少一次WebSearch。若独立证据不可得就明确核心缺口，不许凑出处。

可从 Python 官方 glossary 的 global interpreter lock 和 https://realpython.com/python-gil/ 定位原文。每条只写一个简洁实体；free-threaded的例外写notes，不额外创建挂在C01下却只有单源的辅助实体。
