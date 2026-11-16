// 启动里程碑：把前端到达的关键时点回报给本地服务，写入数据目录下的 startup.log。
// 只用于性能实测（双击 → 可输入），不影响业务请求；同名里程碑只上报一次。
// 与服务端一致要求携带 bridge token：否则本机任意进程都能伪造启动日志。
import { bridgeToken } from "../bridge/client";

const sent = new Set<string>();

export function mark(name: string): void {
  if (sent.has(name)) return;
  sent.add(name);
  void bridgeToken()
    .then((token) =>
      fetch(`/__mark?name=${encodeURIComponent(name)}`, {
        cache: "no-store",
        headers: token ? { "X-NexLing-Token": token } : {},
      }),
    )
    .catch(() => {
      // 忽略：里程碑失败不应影响界面
    });
}
