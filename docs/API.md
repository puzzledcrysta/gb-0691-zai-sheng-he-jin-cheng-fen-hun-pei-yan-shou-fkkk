# 接口

`POST /api/run`：JSON中的csv文本，省略使用样例；或multipart字段file。最大5MB。可附带 orders（订单CSV文本或对象数组）、now（判定时刻ISO8601，省略取当前UTC）、retest_hours（补测时长小时，默认8）。

`POST /api/m1`至`POST /api/m8`：独立运行到指定模块，JSON结构同运行接口；m8 同样接受 orders/now/retest_hours。

`GET /api/history`：历史批次。`POST /api/review`接收id、revision和decision（通过或退回）。`GET /api/evidence.csv`提供单一证据导出。

结构错误422，版本变化409，文件过大413；错误返回code与message。所有页面可从左侧八个模块入口访问。

`GET /api/runs/<id>`读取指定批次；页面与证据CSV通过run_id查询参数绑定批次，模块导航保留该参数。

JSON请求体必须是对象，数组、标量、null、损坏JSON及错误上传字段返回400，且不运行默认样例。

## 截单放行（M8）

`POST /api/releases`：开立放行单，字段 run_id、batch、grade（高牌号/低牌号）、idem_key。
服务端按该批次第8阶段结果复核：牌号完整区间必须全部合格、且存在该牌号未截单订单，否则422；炉次已有放行单返回409（code=RELEASE_CONFLICT）；同一 idem_key 重试返回原单不新增，idem_key 改用于不同请求返回409（code=IDEMPOTENT）。成功返回201与放行单。
`GET /api/releases`：全部放行单，`GET /api/releases?batch=<炉次>`按炉次过滤。

订单CSV列固定为 order_id,grade,batch,cutoff；牌号仅支持高牌号/低牌号，cutoff 为 ISO8601 UTC 时间。同炉次同牌号重复订单保留最晚截单。
