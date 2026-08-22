# Baidu Maps MCP Provider 接入方案

> 实施状态（2026-08-22）：统一 Provider 接口、MCP Streamable HTTP 客户端、三种路由模式、受控 fallback、来源标记与单元测试均已完成。真实 AK 联调仍通过独立探针按需执行，不进入默认测试和 CI。

## 目标

当前选址模块通过 `BaiduMapClient` 直接调用百度地图 WebAPI。MCP 接入不替换现有稳定链路，而是作为能力补充，并在部分 WebAPI 失败场景下作为兜底 Provider。

目标结构：

```text
LocationAnalysisService
  -> LocationProvider
      -> BaiduWebApiProvider   # 当前 WebAPI 能力
      -> BaiduMcpProvider      # 官方 MCP Server 能力
  -> PoiCollector / CandidateGenerator / Scorer / Evidence
```

业务层继续处理候选点生成、竞品采集、特征构造、评分、快照、降级和 Evidence 校验，不直接感知 MCP 工具名或传输协议。

## 官方能力确认

百度地图官方 MCP Server 仓库：`https://github.com/baidu-maps/mcp`

官方远程端点：

```text
https://mcp.map.baidu.com/mcp?ak=<BAIDU_AK>
https://mcp.map.baidu.com/sse?ak=<BAIDU_AK>
```

对餐饮选址最有价值的工具：

- `map_geocode`: 地址转坐标。
- `map_reverse_geocode`: 坐标补行政区和地址语义。
- `map_search_places`: 查竞品、商场、社区、学校、写字楼、地铁站等 POI。
- `map_place_details`: 补 POI 详情、评分、营业时间、价格等字段。
- `map_directions_matrix`: 批量计算候选点到交通节点或商圈的距离和耗时。
- `map_road_traffic`: 后续补充交通拥堵特征。

## 接入原则

1. WebAPI 继续作为核心批量采集通道。

当前 `PoiCollector` 会按关键词、半径和分页做多轮稳定查询，WebAPI 更适合高频、结构固定、可控分页的采集。

2. MCP 优先作为能力补充。

第一批适合通过 MCP 扩展的能力是 `map_place_details` 和 `map_directions_matrix`，用于增强 POI 详情和候选点可达性，而不是立即替换现有竞品采集。

3. MCP 只在部分场景作为兜底。

可以兜底的情况：

- WebAPI 临时网络错误或 retryable 错误。
- WebAPI 单个详情接口缺字段，但 MCP 详情工具可返回补充信息。
- 需要路线矩阵、实时路况等当前 WebAPI Client 尚未封装的能力。

不建议兜底的情况：

- AK 未配置、鉴权失败、IP 白名单限制、权限未开通、额度耗尽。
- WebAPI 返回的是业务参数错误，例如坐标、半径或城市不合法。
- MCP 返回结果无法归一化为当前 `BaiduPoiSearchResult` / `BaiduPoi` 契约。

这些场景应继续走现有 failed/degraded/fallback 机制，避免把 Provider 问题伪装成完整分析。

## Provider 设计

先定义统一能力接口：

```python
class LocationProvider(Protocol):
    def geocode(...): ...
    def suggest_places(...): ...
    def search_nearby_page(...): ...
    def search_region_page(...): ...
```

现有 `BaiduMapClient` 作为 `BaiduWebApiProvider` 使用。`BaiduMcpProvider` 内部负责：

```text
call_tool("map_search_places", args)
  -> 读取 TextContent.text
  -> json.loads
  -> 字段归一化
  -> BaiduPoiSearchResult
```

MCP 原始返回不得直接进入评分层。

## 最小探针

已新增独立探针：

```text
backend/scripts/probe_baidu_mcp.py
```

用途：

- 验证 Streamable HTTP endpoint 是否可用。
- 执行 MCP `initialize`。
- 发送 `notifications/initialized`。
- 执行 `tools/list`。
- 可选调用 `map_geocode`。
- 可选调用 `map_search_places`。
- 输出原始 TextContent，供后续设计归一化逻辑。

示例：

```bash
cd backend
BAIDU_MAP_AK=<your-ak> python scripts/probe_baidu_mcp.py

BAIDU_MAP_AK=<your-ak> python scripts/probe_baidu_mcp.py \
  --address "成都市武侯区天府三街" \
  --city "成都市"

BAIDU_MAP_AK=<your-ak> python scripts/probe_baidu_mcp.py \
  --query "奶茶" \
  --latitude 30.5728 \
  --longitude 104.0668 \
  --radius 800
```

如果使用自定义 endpoint：

```bash
BAIDU_MAP_AK=<your-ak> \
BAIDU_MAP_MCP_URL=https://mcp.map.baidu.com/mcp \
python scripts/probe_baidu_mcp.py
```

## 真实环境验收标准

使用真实 AK 上线前，探针至少要确认：

1. `initialize` 成功返回 server info 和 capabilities。
2. `tools/list` 包含 `map_search_places`、`map_geocode`、`map_place_details`、`map_directions_matrix`。
3. `map_search_places` 返回的 JSON 中存在可稳定映射的 `uid`、`name`、`location`、`address`、`distance` 或等价字段。
4. MCP 错误可映射到现有 `BaiduMapResponseError` 的 kind/retryable 体系。
5. 相同查询下，MCP 与 WebAPI 的 POI 数量和字段覆盖率没有明显劣化。

## 已实现范围

1. `LocationProvider` 统一 WebAPI 与 MCP 的地理编码、区域检索、周边检索和候选点能力。
2. MCP response normalizer 将文本或结构化响应映射为现有 POI 契约，原始响应不进入评分层。
3. `BAIDU_MAP_PROVIDER` 支持 `webapi`、`mcp`、`webapi_with_mcp_fallback`，默认仍为 `webapi`。
4. 组合模式只对 retryable WebAPI 错误执行 MCP fallback；鉴权、配额、权限和参数错误直接暴露。
5. 结果携带 `provider`、`pagination_supported` 与 `provider_warning`，供快照和 Evidence 保留来源与能力差异。
6. MCP 额外封装地点详情与路线矩阵，后续可直接用于候选点详情和可达性特征。

尚需真实环境完成的工作仅是：使用项目 AK 跑探针、保存脱敏契约样例，并对同一查询比较 MCP 与 WebAPI 的字段覆盖率和结果数量。
