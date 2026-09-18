"""Agent 封装：把流式 runtime 包装成可复用的同步/流式接口。"""
from . import runtime


class AgentError(runtime.AgentError):
    pass


class Agent:
    """以角色配置为中心的 Agent：持有只读工具快照与输出校验，支持流式生成。

    - stream(task, context): 生成器，依次产出 runtime.stream_call 的事件 dict
      （delta/tool/result/error）。
    - run(task, context): 同步便捷方法，拼接所有 delta，返回最终通过校验的 value；
      无 result 事件则抛 AgentError。
    """

    def __init__(self, role, tools=None, check=None):
        self.role = role
        self.tools = tools or {}
        self.check = check

    def stream(self, task, context, audit=None):
        yield from runtime.stream_call(self.role, task, context, tools=self.tools, check=self.check, audit=audit)

    def run(self, task, context, audit=None):
        parts = []
        for event in self.stream(task, context, audit=audit):
            if event['type'] == 'delta':
                parts.append(event['text'])
            elif event['type'] == 'result':
                return event['value']
            elif event['type'] == 'error':
                raise AgentError(event['message'])
        raise AgentError('模型未返回有效结果')
