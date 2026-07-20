<template>
  <div class="simulation-panel">
    <!-- 决策总控：推演全部 Run -->
    <div class="decision-bar">
      <div class="decision-meta">
        <span class="decision-label">推演全部</span>
        <span class="decision-progress mono">
          {{ runProgress.done || 0 }}/{{ runProgress.total || totalRunCount || '—' }}
        </span>
        <span class="decision-phase" :class="decisionPhaseClass">{{ decisionPhaseLabel }}</span>
      </div>
      <div class="action-controls">
        <button
          v-if="phase === 1"
          class="action-btn danger"
          :disabled="isStopping || isStarting"
          @click="handleStopSimulation"
        >
          {{ isStopping ? $t('step3.stoppingBtn') : $t('step3.stopSimBtn') }}
        </button>
        <button
          v-if="phase === 2 || phase === 0"
          class="action-btn secondary"
          :disabled="isStarting || isStopping"
          @click="handleRestartAll"
        >
          {{ isStarting && restartScope === 'all' ? '启动中…' : (showRunMatrix ? '重新推演全部' : '重新推演') }}
        </button>
        <button
          class="action-btn primary"
          :disabled="phase !== 2 || isGeneratingReport"
          @click="handleNextStep"
        >
          <span v-if="isGeneratingReport" class="loading-spinner-small"></span>
          {{ isGeneratingReport ? $t('step3.generatingReportBtn') : $t('step3.startGenerateReportBtn') }}
          <span v-if="!isGeneratingReport" class="arrow-icon">→</span>
        </button>
      </div>
    </div>

    <!-- Scenario × Run 舰队视图（N>1） -->
    <RunMatrixPanel
      :matrix="runMatrix"
      :progress="runProgress"
      :selected-run-id="selectedRunId"
      :selected-sim-id="selectedSimId"
      @select="onSelectRun"
    />

    <!-- Run 检视：平台进度属于当前选中 Run -->
    <div class="run-inspector">
      <div class="inspector-head">
        <div class="inspector-title">
          <template v-if="showRunMatrix">
            <span class="inspector-kicker">正在查看</span>
            <span class="inspector-name">{{ selectedRunLabel }}</span>
          </template>
          <template v-else>
            <span class="inspector-name">推演详情</span>
          </template>
        </div>
        <div class="inspector-actions">
          <button
            v-if="showRunMatrix && userPinnedRun && phase === 1 && hasLiveRun"
            type="button"
            class="follow-live-btn"
            @click="followLiveRun"
          >
            跟随进行中
          </button>
          <button
            v-if="showRunMatrix && (phase === 2 || phase === 0) && selectedSimId"
            type="button"
            class="follow-live-btn"
            :disabled="isStarting || isStopping"
            @click="handleRestartSelectedRun"
          >
            {{ isStarting && restartScope === 'run' ? '启动中…' : '重跑此 Run' }}
          </button>
        </div>
      </div>

      <div v-if="isGtvMode" class="gtv-progress">
        <div class="gtv-progress-head">
          <span class="mono">GTV 双轨推演</span>
          <span class="gtv-badge" :class="decisionPhaseClass">{{ decisionPhaseLabel }}</span>
        </div>
        <p class="gtv-progress-desc">
          {{ $t('step3.gtvWorldSampleNote') }} · Agent 走漏斗时间线 · 统计轨用方案 KPI / 三榜对照（非社媒发帖 · 谈价≠公司改挂牌价）
        </p>
        <div class="gtv-round-row mono">
          <span>Agent R{{ gtvCurrentRound }}/{{ gtvTotalRounds }}</span>
          <span v-if="agentStatusMsg" class="gtv-agent-msg">{{ agentStatusMsg }}</span>
        </div>
        <div class="gtv-progress-bar">
          <div
            class="gtv-progress-fill"
            :style="{ width: gtvProgressPercent + '%' }"
          ></div>
        </div>
        <div class="gtv-progress-meta mono">
          {{ gtvProgressPercent }}% · 统计轨
          {{ scenarioScores ? (scenarioScores.mode === 'model' ? '已出分' : '缓存/进行中') : '等待中' }}
          <template v-if="agentTrackFailed"> · Agent 不可用</template>
        </div>
      </div>

      <div v-if="isGtvMode" class="platform-row">
        <div
          class="platform-status twitter"
          :class="{
            active: phase === 1 && !agentTrackFailed,
            completed: phase === 2 || agentTrackFailed,
          }"
        >
          <div class="platform-header">
            <span class="platform-name">成交 Agent</span>
            <span v-if="phase === 2 || agentTrackFailed" class="status-badge">
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="3">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </span>
          </div>
          <div class="platform-stats">
            <span class="stat">
              <span class="stat-label">ROUND</span>
              <span class="stat-value mono">{{ gtvCurrentRound }}<span class="stat-total">/{{ gtvTotalRounds }}</span></span>
            </span>
            <span class="stat">
              <span class="stat-label">ACTS</span>
              <span class="stat-value mono">{{ agentActionsCount }}</span>
            </span>
          </div>
          <div class="actions-tooltip">
            <div class="tooltip-title">漏斗动作</div>
            <div class="tooltip-actions">
              <span class="tooltip-action">线索</span>
              <span class="tooltip-action">项目</span>
              <span class="tooltip-action">跟进</span>
              <span class="tooltip-action">报备</span>
              <span class="tooltip-action">锁客</span>
              <span class="tooltip-action">约看</span>
              <span class="tooltip-action">带看</span>
              <span class="tooltip-action">意向</span>
              <span class="tooltip-action">谈价|直签</span>
              <span class="tooltip-action">审批</span>
              <span class="tooltip-action">计租</span>
              <span class="tooltip-action">回款</span>
            </div>
          </div>
        </div>

        <div
          class="platform-status reddit"
          :class="{
            active: phase === 1 && !scenarioScores,
            completed: !!scenarioScores,
          }"
        >
          <div class="platform-header">
            <span class="platform-name">统计模型</span>
            <span v-if="scenarioScores" class="status-badge">
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="3">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </span>
          </div>
          <div class="platform-stats">
            <span class="stat">
              <span class="stat-label">MODE</span>
              <span class="stat-value mono">{{ scenarioScores?.mode || '—' }}</span>
            </span>
            <span class="stat">
              <span class="stat-label">方案</span>
              <span class="stat-value mono">{{ gtvStatScenarioCount }}</span>
            </span>
          </div>
          <div class="actions-tooltip">
            <div class="tooltip-title">统计对照（非时间线）</div>
            <div class="tooltip-actions">
              <span class="tooltip-action">三榜</span>
              <span class="tooltip-action">期望合同</span>
              <span class="tooltip-action">期望佣金</span>
              <span class="tooltip-action">what-if</span>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="platform-row">
        <div class="platform-status twitter" :class="{ active: runStatus.twitter_running, completed: runStatus.twitter_completed }">
          <div class="platform-header">
            <svg class="platform-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
            </svg>
            <span class="platform-name">Info Plaza</span>
            <span v-if="runStatus.twitter_completed" class="status-badge">
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="3">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </span>
          </div>
          <div class="platform-stats">
            <span class="stat">
              <span class="stat-label">ROUND</span>
              <span class="stat-value mono">{{ runStatus.twitter_current_round || 0 }}<span class="stat-total">/{{ runStatus.total_rounds || maxRounds || '-' }}</span></span>
            </span>
            <span class="stat">
              <span class="stat-label">TIME</span>
              <span class="stat-value mono">{{ twitterElapsedTime }}</span>
            </span>
            <span class="stat">
              <span class="stat-label">ACTS</span>
              <span class="stat-value mono">{{ runStatus.twitter_actions_count || 0 }}</span>
            </span>
          </div>
          <div class="actions-tooltip">
            <div class="tooltip-title">Available Actions</div>
            <div class="tooltip-actions">
              <span class="tooltip-action">POST</span>
              <span class="tooltip-action">LIKE</span>
              <span class="tooltip-action">REPOST</span>
              <span class="tooltip-action">QUOTE</span>
              <span class="tooltip-action">FOLLOW</span>
              <span class="tooltip-action">IDLE</span>
            </div>
          </div>
        </div>

        <div class="platform-status reddit" :class="{ active: runStatus.reddit_running, completed: runStatus.reddit_completed }">
          <div class="platform-header">
            <svg class="platform-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path>
            </svg>
            <span class="platform-name">Topic Community</span>
            <span v-if="runStatus.reddit_completed" class="status-badge">
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="3">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </span>
          </div>
          <div class="platform-stats">
            <span class="stat">
              <span class="stat-label">ROUND</span>
              <span class="stat-value mono">{{ runStatus.reddit_current_round || 0 }}<span class="stat-total">/{{ runStatus.total_rounds || maxRounds || '-' }}</span></span>
            </span>
            <span class="stat">
              <span class="stat-label">TIME</span>
              <span class="stat-value mono">{{ redditElapsedTime }}</span>
            </span>
            <span class="stat">
              <span class="stat-label">ACTS</span>
              <span class="stat-value mono">{{ runStatus.reddit_actions_count || 0 }}</span>
            </span>
          </div>
          <div class="actions-tooltip">
            <div class="tooltip-title">Available Actions</div>
            <div class="tooltip-actions">
              <span class="tooltip-action">POST</span>
              <span class="tooltip-action">COMMENT</span>
              <span class="tooltip-action">LIKE</span>
              <span class="tooltip-action">DISLIKE</span>
              <span class="tooltip-action">SEARCH</span>
              <span class="tooltip-action">TREND</span>
              <span class="tooltip-action">FOLLOW</span>
              <span class="tooltip-action">MUTE</span>
              <span class="tooltip-action">REFRESH</span>
              <span class="tooltip-action">IDLE</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- GTV：统计面板（KPI/榜单）+ Agent 时间线；其它模板仍为双平台时间线 -->
    <div class="main-content-area" ref="scrollContainer" @scroll="onTimelineScroll">
      <section v-if="isGtvMode" class="gtv-stat-panel">
        <div class="gtv-stat-head">
          <div class="gtv-stat-title">
            <span class="mono">统计模型对照</span>
            <span class="gtv-stat-sub">历史模型 what-if · 非漏斗过程 · 非因果</span>
          </div>
          <span v-if="scenarioScores" class="gtv-stat-mode mono">{{ scenarioScores.mode || 'model' }}</span>
          <span v-else class="gtv-stat-mode mono is-wait">打分中…</span>
        </div>

        <div v-if="!scenarioScores" class="gtv-stat-empty">
          <div class="gtv-stat-skel"></div>
          <p>统计轨出分后在此展示方案经济量与三榜，不写入时间线。</p>
        </div>

        <template v-else>
          <div v-if="gtvStatScenarios.length > 1" class="gtv-stat-tabs" role="tablist">
            <button
              v-for="(s, idx) in gtvStatScenarios"
              :key="s.scenario_id || s.name || idx"
              type="button"
              role="tab"
              class="gtv-stat-tab"
              :class="{ active: idx === gtvStatScenarioIdx }"
              :aria-selected="idx === gtvStatScenarioIdx"
              @click="gtvStatScenarioIdx = idx"
            >
              {{ shortStatScenarioName(s, idx) }}
            </button>
          </div>

          <div v-if="selectedStatScenario" class="gtv-stat-kpis">
            <div class="gtv-kpi">
              <span class="gtv-kpi-label">预期成交</span>
              <span class="gtv-kpi-val mono">{{ fmtStat(selectedStatScenario.summary?.expected_deals, 2) }}</span>
            </div>
            <div class="gtv-kpi">
              <span class="gtv-kpi-label">期望合同额</span>
              <span class="gtv-kpi-val mono">{{ fmtStat(selectedStatScenario.summary?.expected_contract_money, 0) }}</span>
            </div>
            <div class="gtv-kpi">
              <span class="gtv-kpi-label">期望佣金</span>
              <span class="gtv-kpi-val mono">{{ fmtStat(selectedStatScenario.summary?.expected_commission, 0) }}</span>
            </div>
            <div class="gtv-kpi">
              <span class="gtv-kpi-label">较 Baseline</span>
              <span
                class="gtv-kpi-val mono"
                :class="statDeltaClass(selectedStatScenario)"
              >{{ fmtStatContractDelta(selectedStatScenario) }}</span>
            </div>
          </div>

          <div class="gtv-stat-boards">
            <div class="gtv-board">
              <div class="gtv-board-head mono">房源榜 Top{{ Math.min(8, selectedStatListings.length || 8) }}</div>
              <table v-if="selectedStatListings.length" class="gtv-board-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>房源</th>
                    <th>类型</th>
                    <th>城市</th>
                    <th>成交分</th>
                    <th>质量</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, ri) in selectedStatListings" :key="row.listing_id || ri">
                    <td class="mono">{{ ri + 1 }}</td>
                    <td>
                      <div class="gtv-board-name">{{ row.listing_name || '—' }}</div>
                      <div class="gtv-board-id mono" :title="row.listing_id">{{ row.listing_id || '' }}</div>
                      <div v-if="row.address" class="gtv-board-addr">{{ row.address }}</div>
                    </td>
                    <td>{{ listingTypeZh(row.listing_type) }}</td>
                    <td>{{ row.city_name || '—' }}</td>
                    <td class="mono">{{ fmtStat(row.score, 3) }}</td>
                    <td class="mono">{{ row.quality_score != null ? fmtStat(row.quality_score, 2) : '—' }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-else class="gtv-board-empty">暂无房源榜</p>
            </div>

            <div class="gtv-board">
              <div class="gtv-board-head mono">经纪人榜 Top{{ Math.min(5, selectedStatBrokers.length || 5) }}</div>
              <table v-if="selectedStatBrokers.length" class="gtv-board-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>经纪人</th>
                    <th>成交分</th>
                    <th>历史开单</th>
                    <th>在管</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, bi) in selectedStatBrokers" :key="row.user_id || bi">
                    <td class="mono">{{ bi + 1 }}</td>
                    <td>
                      <div class="gtv-board-name">{{ row.nick_name || row.user_name || '—' }}</div>
                      <div class="gtv-board-id mono" :title="row.user_id">{{ row.user_id || '' }}</div>
                    </td>
                    <td class="mono">{{ fmtStat(row.score, 3) }}</td>
                    <td class="mono">{{ fmtStat(row.hist_deals, 0) }}</td>
                    <td class="mono">{{ fmtStat(row.n_listings, 0) }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-else class="gtv-board-empty">暂无经纪人榜</p>
            </div>
          </div>
        </template>
      </section>

      <div class="timeline-header" v-if="allActions.length > 0 || selectedRunShort || isGtvMode">
        <div class="timeline-stats">
          <span class="total-count">
            <template v-if="isGtvMode">Agent 漏斗事件</template>
            <template v-else>EVENTS<span v-if="selectedRunShort"> · {{ selectedRunShort }}</span></template>
            <template v-if="!isGtvMode">:</template>
            <span class="mono">{{ isGtvMode ? agentActionsCount : allActions.length }}</span>
          </span>
          <span v-if="isGtvMode" class="platform-breakdown">
            <span class="breakdown-item twitter">
              <span class="gtv-track-tag">时间线仅 Agent</span>
            </span>
          </span>
          <span v-else class="platform-breakdown">
            <span class="breakdown-item twitter">
              <svg class="mini-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>
              <span class="mono">{{ twitterActionsCount }}</span>
            </span>
            <span class="breakdown-divider">/</span>
            <span class="breakdown-item reddit">
              <svg class="mini-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
              <span class="mono">{{ redditActionsCount }}</span>
            </span>
          </span>
        </div>
      </div>
      
      <!-- Timeline Feed -->
      <div class="timeline-feed" :class="{ 'gtv-agent-feed': isGtvMode }">
        <div class="timeline-axis"></div>
        
        <TransitionGroup name="timeline-item">
          <div 
            v-for="action in chronologicalActions" 
            :key="action._uniqueId || action.id || `${action.timestamp}-${action.agent_id}`" 
            class="timeline-item"
            :class="action.platform"
          >
            <div class="timeline-marker">
              <div class="marker-dot"></div>
            </div>
            
            <div class="timeline-card">
              <div class="card-header">
                <div class="agent-info">
                  <div class="avatar-placeholder">{{ (action.agent_name || 'A')[0] }}</div>
                  <span class="agent-name">{{ action.agent_name }}</span>
                </div>
                
                <div class="header-meta">
                  <div class="platform-indicator">
                    <span v-if="action.platform === 'agent'" class="gtv-track-tag">Agent</span>
                    <span v-else-if="action.platform === 'stat'" class="gtv-track-tag">统计</span>
                    <svg v-else-if="action.platform === 'twitter'" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>
                    <svg v-else viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
                  </div>
                  <div class="action-badge" :class="getActionTypeClass(action.action_type)">
                    {{ action.action_args?.stage_label || getActionTypeLabel(action.action_type) }}
                  </div>
                </div>
              </div>
              
              <div class="card-body">
                <!-- GTV Agent：状态 + 房源/经纪人实体 -->
                <div
                  v-if="action.action_type === 'DEAL_ACTION' && (action.action_args?.listing_id || action.action_args?.broker_id)"
                  class="gtv-entity-meta"
                >
                  <div class="gtv-entity-row">
                    <span class="gtv-entity-k">状态</span>
                    <span class="gtv-entity-v mono">{{ action.action_args?.stage_label || action.action_args?.stage || '—' }}</span>
                    <span
                      v-if="action.action_args?.from_stage_label && action.action_args.from_stage_label !== action.action_args.stage_label"
                      class="gtv-entity-from mono"
                    >← {{ action.action_args.from_stage_label }}</span>
                  </div>
                  <div v-if="action.action_args?.listing_id" class="gtv-entity-row">
                    <span class="gtv-entity-k">房源</span>
                    <span class="gtv-entity-v">{{ action.action_args.listing_name || '—' }}</span>
                    <span class="gtv-entity-id mono" :title="action.action_args.listing_id">ID {{ action.action_args.listing_id }}</span>
                  </div>
                  <div v-if="action.action_args?.broker_id || action.action_args?.broker_name" class="gtv-entity-row">
                    <span class="gtv-entity-k">经纪人</span>
                    <span class="gtv-entity-v">{{ action.action_args.broker_name || action.agent_name || '—' }}</span>
                    <span v-if="action.action_args?.broker_id" class="gtv-entity-id mono" :title="action.action_args.broker_id">ID {{ action.action_args.broker_id }}</span>
                  </div>
                  <div class="gtv-entity-row">
                    <span class="gtv-entity-k">地址</span>
                    <span class="gtv-entity-v">{{ action.action_args?.amap_address || action.action_args?.address || action.action_args?.city || '—' }}</span>
                  </div>
                  <div class="gtv-entity-row">
                    <span class="gtv-entity-k">坐标</span>
                    <span class="gtv-entity-v mono">
                      <template v-if="action.action_args?.longitude != null && action.action_args?.latitude != null">
                        {{ Number(action.action_args.longitude).toFixed(5) }}, {{ Number(action.action_args.latitude).toFixed(5) }}
                      </template>
                      <template v-else>—</template>
                    </span>
                  </div>
                  <div class="gtv-entity-row">
                    <span class="gtv-entity-k">质量</span>
                    <span class="gtv-entity-v">{{ action.action_args?.quality_highlights || (action.action_args?.quality_score != null ? `质量分 ${Number(action.action_args.quality_score).toFixed(2)}` : '—') }}</span>
                  </div>
                </div>
                <!-- GTV Agent 漏斗事件正文 -->
                <div
                  v-if="action.action_type === 'DEAL_ACTION' && action.action_args?.content"
                  class="content-text main-text"
                >
                  {{ action.action_args.content }}
                </div>

                <!-- CREATE_POST: 发布帖子 -->
                <div v-if="action.action_type === 'CREATE_POST' && action.action_args?.content" class="content-text main-text">
                  {{ action.action_args.content }}
                </div>

                <!-- QUOTE_POST: 引用帖子 -->
                <template v-if="action.action_type === 'QUOTE_POST'">
                  <div v-if="action.action_args?.quote_content || action.action_args?.content || action.content" class="content-text">
                    {{ action.action_args?.quote_content || action.action_args?.content || action.content }}
                  </div>
                  <div v-if="action.action_args?.original_content" class="quoted-block">
                    <div class="quote-header">
                      <svg class="icon-small" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>
                      <span class="quote-label">@{{ action.action_args.original_author_name || 'User' }}</span>
                    </div>
                    <div class="quote-text">
                      {{ truncateContent(action.action_args.original_content, 150) }}
                    </div>
                  </div>
                  <div v-else class="idle-info">
                    <span class="idle-label">引用了帖子 #{{ action.action_args?.quoted_id || action.parent_post_id || '—' }}</span>
                  </div>
                </template>

                <!-- REPOST: 转发帖子 -->
                <template v-if="action.action_type === 'REPOST'">
                  <div class="repost-info">
                    <svg class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="17 1 21 5 17 9"></polyline><path d="M3 11V9a4 4 0 0 1 4-4h14"></path><polyline points="7 23 3 19 7 15"></polyline><path d="M21 13v2a4 4 0 0 1-4 4H3"></path></svg>
                    <span class="repost-label">Reposted from @{{ action.action_args?.original_author_name || 'User' }}</span>
                  </div>
                  <div v-if="action.action_args?.original_content" class="repost-content">
                    {{ truncateContent(action.action_args.original_content, 200) }}
                  </div>
                </template>

                <!-- LIKE_POST / DISLIKE_POST: 点赞/踩帖子 -->
                <template v-if="action.action_type === 'LIKE_POST' || action.action_type === 'DISLIKE_POST'">
                  <div class="like-info">
                    <svg class="icon-small filled" viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
                    <span class="like-label">
                      {{ action.action_type === 'DISLIKE_POST' ? 'Disliked' : 'Liked' }}
                      @{{ action.action_args?.post_author_name || 'User' }}'s post
                      <template v-if="!action.action_args?.post_content && (action.action_args?.like_id || action.action_args?.post_id || action.action_args?.dislike_id)">
                        #{{ action.action_args?.like_id || action.action_args?.dislike_id || action.action_args?.post_id }}
                      </template>
                    </span>
                  </div>
                  <div v-if="action.action_args?.post_content" class="liked-content">
                    "{{ truncateContent(action.action_args.post_content, 120) }}"
                  </div>
                </template>

                <!-- CREATE_COMMENT: 发表评论 -->
                <template v-if="action.action_type === 'CREATE_COMMENT'">
                  <div v-if="action.action_args?.content" class="content-text">
                    {{ action.action_args.content }}
                  </div>
                  <div v-if="action.action_args?.post_id" class="comment-context">
                    <svg class="icon-small" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
                    <span>Reply to post #{{ action.action_args.post_id }}</span>
                  </div>
                </template>

                <!-- SEARCH_POSTS: 搜索帖子 -->
                <template v-if="action.action_type === 'SEARCH_POSTS'">
                  <div class="search-info">
                    <svg class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                    <span class="search-label">Search Query:</span>
                    <span class="search-query">"{{ action.action_args?.query || '' }}"</span>
                  </div>
                </template>

                <!-- FOLLOW: 关注用户 -->
                <template v-if="action.action_type === 'FOLLOW'">
                  <div class="follow-info">
                    <svg class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="8.5" cy="7" r="4"></circle><line x1="20" y1="8" x2="20" y2="14"></line><line x1="23" y1="11" x2="17" y2="11"></line></svg>
                    <span class="follow-label">Followed @{{ action.action_args?.target_user || action.action_args?.user_id || 'User' }}</span>
                  </div>
                </template>

                <!-- UPVOTE / DOWNVOTE -->
                <template v-if="action.action_type === 'UPVOTE_POST' || action.action_type === 'DOWNVOTE_POST'">
                  <div class="vote-info">
                    <svg v-if="action.action_type === 'UPVOTE_POST'" class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"></polyline></svg>
                    <svg v-else class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
                    <span class="vote-label">{{ action.action_type === 'UPVOTE_POST' ? 'Upvoted' : 'Downvoted' }} Post</span>
                  </div>
                  <div v-if="action.action_args?.post_content" class="voted-content">
                    "{{ truncateContent(action.action_args.post_content, 120) }}"
                  </div>
                </template>

                <!-- DO_NOTHING: 无操作（静默） -->
                <template v-if="action.action_type === 'DO_NOTHING'">
                  <div class="idle-info">
                    <svg class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                    <span class="idle-label">Action Skipped</span>
                  </div>
                </template>

                <!-- 通用回退：未知类型或有 content 但未被上述处理 -->
                <div v-if="!['DEAL_ACTION', 'STAT_SCORE', 'CREATE_POST', 'QUOTE_POST', 'REPOST', 'LIKE_POST', 'DISLIKE_POST', 'CREATE_COMMENT', 'SEARCH_POSTS', 'FOLLOW', 'UPVOTE_POST', 'DOWNVOTE_POST', 'DO_NOTHING'].includes(action.action_type) && action.action_args?.content" class="content-text">
                  {{ action.action_args.content }}
                </div>
              </div>

              <div class="card-footer">
                <span class="time-tag">R{{ action.round_num }} • {{ formatActionTime(action.timestamp) }}</span>
                <!-- Platform tag removed as it is in header now -->
              </div>
            </div>
          </div>
        </TransitionGroup>

        <div v-if="allActions.length === 0" class="waiting-state">
          <div class="pulse-ring"></div>
          <span>{{ isGtvMode ? '等待成交 Agent 漏斗事件…' : 'Waiting for agent actions...' }}</span>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  startSimulation,
  stopSimulation,
  getRunStatus,
  getRunStatusDetail,
  getEnvStatus,
} from '../api/simulation'
import { getDecision } from '../api/decision'
import { generateReport } from '../api/report'
import { subscribeDecision } from '../api/sse'
import RunMatrixPanel from './RunMatrixPanel.vue'
import { touchWorkflowStep, syncWorkflowFromServer } from '../store/workflowContext'
import { taskRoute } from '../utils/taskRoute'

const { t } = useI18n()

const props = defineProps({
  decisionId: String,
  simulationId: String, // 真实 sim_*（可选）
  maxRounds: Number, // 从Step2传入的最大轮数
  minutesPerRound: {
    type: Number,
    default: 30 // 默认每轮30分钟
  },
  projectData: Object,
  graphData: Object,
  systemLogs: Array
})

/** 业务任务 ID：优先 decisionId */
const workflowId = computed(() => props.decisionId || props.simulationId)

const emit = defineEmits(['go-back', 'next-step', 'add-log', 'update-status'])

const router = useRouter()

// State
const isGeneratingReport = ref(false)
const runMatrix = ref([])
const runProgress = ref({ done: 0, total: 0 })
const selectedRunId = ref(null)
const selectedSimId = ref(null)
/** 用户点矩阵选中后不再自动跳到其它 Run */
const userPinnedRun = ref(false)
const phase = ref(0) // 0: 未开始, 1: 运行中, 2: 已完成
const sceneTemplate = ref('')
const dealTimeline = ref(null)
const scenarioScores = ref(null)
const agentStatus = ref(null)
const isGtvMode = computed(() => String(sceneTemplate.value || '').toLowerCase() === 'gtv_deal')
const gtvCurrentRound = computed(() => {
  const a = Number(agentStatus.value?.current_round)
  if (!Number.isNaN(a) && a > 0) return a
  return Number(runStatus.value?.current_round || runStatus.value?.twitter_current_round || 0)
})
const gtvTotalRounds = computed(() => {
  const a = Number(agentStatus.value?.total_rounds)
  if (!Number.isNaN(a) && a > 0) return a
  return Number(runStatus.value?.total_rounds || 16)
})
const agentStatusMsg = computed(() => agentStatus.value?.message || '')
const agentTrackFailed = computed(
  () => String(agentStatus.value?.status || '').toLowerCase() === 'failed',
)
const gtvProgressPercent = computed(() => {
  const agSt = String(agentStatus.value?.status || '').toLowerCase()
  // Agent 仍在跑时绝不以 100% 冒充整局完成（统计出分 ≠ Agent 跑完）
  if (agSt === 'running') {
    const tot = gtvTotalRounds.value || 16
    const cur = gtvCurrentRound.value || 0
    if (tot > 0 && cur > 0) return Math.min(95, Math.round((cur / tot) * 100))
    return scenarioScores.value ? 35 : 15
  }
  if (phase.value === 2 || agSt === 'completed' || agSt === 'failed') return 100
  if (phase.value === 1) {
    const tot = gtvTotalRounds.value || 16
    const cur = gtvCurrentRound.value || 0
    if (tot > 0 && cur > 0) return Math.min(99, Math.round((cur / tot) * 100))
    if (scenarioScores.value) return 40
    return 15
  }
  return 0
})
function fmtStat(v, digits = 0) {
  const n = Number(v)
  if (v == null || Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
}
function fmtDelta(v) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${fmtStat(n, 0)}`
}
function listingTypeZh(t) {
  return (
    { plant: '厂房', warehouse: '仓库', office: '办公' }[String(t || '').toLowerCase()] ||
    t ||
    '房源'
  )
}
function shortStatScenarioName(s, idx) {
  const raw = String(s?.name || '').trim()
  if (s?.is_baseline || /baseline/i.test(String(s?.kind || ''))) return 'Baseline·不干预'
  if (!raw) return `方案${idx + 1}`
  const first = raw.split(/\n/)[0].trim()
  if (first.length > 28 || /推演下一阶段|现实种子/.test(first)) {
    return s?.kind === 'custom' ? `方案${idx + 1}` : `${first.slice(0, 24)}…`
  }
  return first
}
function fmtStatContractDelta(s) {
  if (!s || s.is_baseline) return '—'
  const delta = s.delta_vs_baseline?.expected_contract_money?.abs
  return fmtDelta(delta)
}
function statDeltaClass(s) {
  const delta = Number(s?.delta_vs_baseline?.expected_contract_money?.abs)
  if (Number.isNaN(delta) || delta === 0) return ''
  return delta > 0 ? 'is-up' : 'is-down'
}
const gtvStatScenarioIdx = ref(0)
const isStarting = ref(false)
const isStopping = ref(false)
/** 'all' | 'run' — 用于按钮文案与参数 */
const restartScope = ref('all')
const startError = ref(null)
const runStatus = ref({})
const allActions = ref([]) // 所有动作（增量累积）
const actionIds = ref(new Set()) // 用于去重的动作ID集合
const scrollContainer = ref(null)
/** 贴底时自动滚；用户上滑离开底部后暂停，回到底部再恢复 */
const stickTimelineToBottom = ref(true)
const TIMELINE_BOTTOM_THRESHOLD = 80

// Computed
// 按时间顺序显示动作（最新的在最后面，即底部）
const chronologicalActions = computed(() => {
  return allActions.value
})

// 各平台动作计数
const twitterActionsCount = computed(() => {
  return allActions.value.filter(a => a.platform === 'twitter').length
})

const redditActionsCount = computed(() => {
  return allActions.value.filter(a => a.platform === 'reddit').length
})

const agentActionsCount = computed(() => {
  return allActions.value.filter((a) => a.platform === 'agent').length
})

const gtvStatScenarios = computed(() => scenarioScores.value?.scenarios || [])
const gtvStatScenarioCount = computed(() => gtvStatScenarios.value.length)
const selectedStatScenario = computed(() => {
  const list = gtvStatScenarios.value
  if (!list.length) return null
  const idx = Math.min(Math.max(0, gtvStatScenarioIdx.value), list.length - 1)
  return list[idx]
})
const selectedStatListings = computed(() =>
  (selectedStatScenario.value?.listings || []).slice(0, 8),
)
const selectedStatBrokers = computed(() =>
  (selectedStatScenario.value?.brokers || []).slice(0, 5),
)

watch(gtvStatScenarios, (list) => {
  if (!list?.length) {
    gtvStatScenarioIdx.value = 0
    return
  }
  if (gtvStatScenarioIdx.value >= list.length) gtvStatScenarioIdx.value = 0
})

// 格式化模拟流逝时间（根据轮次和每轮分钟数计算）
const formatElapsedTime = (currentRound) => {
  if (!currentRound || currentRound <= 0) return '0h 0m'
  const totalMinutes = currentRound * props.minutesPerRound
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return `${hours}h ${minutes}m`
}

// Twitter平台的模拟流逝时间
const twitterElapsedTime = computed(() => {
  return formatElapsedTime(runStatus.value.twitter_current_round || 0)
})

// Reddit平台的模拟流逝时间
const redditElapsedTime = computed(() => {
  return formatElapsedTime(runStatus.value.reddit_current_round || 0)
})

const totalRunCount = computed(() =>
  (runMatrix.value || []).reduce((n, sc) => n + ((sc.runs || []).length), 0),
)

const showRunMatrix = computed(() => totalRunCount.value > 1)

const selectedRunMeta = computed(() => {
  for (const sc of runMatrix.value || []) {
    const runs = sc.runs || []
    const idx = runs.findIndex(
      (r) => r.run_id === selectedRunId.value || r.sim_id === selectedSimId.value,
    )
    if (idx >= 0) {
      return {
        scenarioName: sc.scenario_name || sc.kind || '方案',
        runIndex: idx + 1,
        run: runs[idx],
        color: sc.color,
      }
    }
  }
  return null
})

const selectedRunLabel = computed(() => {
  const m = selectedRunMeta.value
  if (!m) return selectedSimId.value || '—'
  return `${m.scenarioName} · R${m.runIndex}`
})

const selectedRunShort = computed(() => {
  const m = selectedRunMeta.value
  if (!m) return ''
  return `${m.scenarioName} R${m.runIndex}`
})

const decisionPhaseLabel = computed(() => {
  if (isStarting.value) return '启动中'
  if (phase.value === 1) return '运行中'
  if (phase.value === 2) return '已完成'
  return '未开始'
})

const decisionPhaseClass = computed(() => {
  if (phase.value === 1) return 'is-running'
  if (phase.value === 2) return 'is-done'
  return 'is-idle'
})

const hasLiveRun = computed(() =>
  (runMatrix.value || []).some((sc) =>
    (sc.runs || []).some((r) =>
      ['running', 'starting'].includes(String(r.status || '').toLowerCase()),
    ),
  ),
)

// Methods
const addLog = (msg) => {
  console.log(`[SandOwl] ${msg}`)
  emit('add-log', msg)
}

// 重置所有状态（用于强制重新启动模拟）
const resetAllState = () => {
  phase.value = 0
  runStatus.value = {}
  runMatrix.value = []
  runProgress.value = { done: 0, total: 0 }
  selectedRunId.value = null
  selectedSimId.value = null
  allActions.value = []
  actionIds.value = new Set()
  dealTimeline.value = null
  scenarioScores.value = null
  agentStatus.value = null
  stickTimelineToBottom.value = true
  prevTwitterRound.value = 0
  prevRedditRound.value = 0
  startError.value = null
  isStarting.value = false
  isStopping.value = false
  userPinnedRun.value = false
  stopPolling()  // 停止之前可能存在的轮询
  stopGtvSidecarPolling()
}

/** 附着已有推演：不 reset、不 force，只拉状态并订 SSE */
const attachRunningSimulation = async ({ completed = false } = {}) => {
  if (!workflowId.value) return
  addLog(completed ? '检测到推演已结束，加载结果…' : '检测到推演进行中，附着进度（不重开）…')
  emit('update-status', completed ? 'completed' : 'processing')
  phase.value = completed ? 2 : 1
  if (isGtvMode.value) {
    await refreshGtvSidecars()
    if (!completed) startGtvSidecarPolling()
  }
  await fetchRunStatus()
  await fetchRunStatusDetail()
  startStatusPolling()
  startDetailPolling()
  // 仅决策级终态才收口；单 sim runner 完成不算
  if (completed || isDecisionComplete(runStatus.value)) {
    phase.value = 2
    emit('update-status', 'completed')
  } else {
    phase.value = 1
    emit('update-status', 'processing')
  }
}

/** 启动推演；force=true 才清日志重开；scope=all|run */
const doStartSimulation = async ({ force = false, scope = 'all' } = {}) => {
  if (!workflowId.value) {
    addLog(t('log.errorMissingSimId'))
    return
  }

  restartScope.value = scope === 'run' ? 'run' : 'all'

  if (force && restartScope.value === 'all') {
    resetAllState()
  } else if (force && restartScope.value === 'run') {
    // 只清当前检视时间线，保持选中钉住
    userPinnedRun.value = true
    allActions.value = []
    actionIds.value = new Set()
    prevTwitterRound.value = 0
    prevRedditRound.value = 0
    stopPolling()
  } else {
    stopPolling()
  }
  
  isStarting.value = true
  startError.value = null
  if (force && restartScope.value === 'run') {
    addLog(`强制重跑当前 Run：${selectedSimId.value || selectedRunId.value || '—'}`)
  } else {
    addLog(force ? '强制重新推演全部 Run…' : t('log.startingDualSim'))
  }
  emit('update-status', 'processing')
  
  try {
    const params = {
      simulation_id: workflowId.value,
      platform: 'parallel',
      force: Boolean(force),
      enable_graph_memory_update: true
    }
    if (force && restartScope.value === 'run') {
      if (!selectedSimId.value && !selectedRunId.value) {
        throw new Error('未选中要重跑的 Run')
      }
      params.only_sim_id = selectedSimId.value || undefined
      params.only_run_id = selectedRunId.value || undefined
    }
    
    if (props.maxRounds) {
      params.max_rounds = props.maxRounds
      addLog(t('log.setMaxRounds', { rounds: props.maxRounds }))
    }
    
    addLog(t('log.graphMemoryUpdateEnabled'))
    
    const res = await startSimulation(params)
    
    if (res.success && res.data) {
      if (res.data.attached) {
        addLog('服务端已在推演，改为附着现有运行')
        await attachRunningSimulation()
        return
      }
      if (res.data.force_restarted) {
        addLog(
          res.data.restart_scope === 'run'
            ? '已清理当前 Run 日志，开始重跑'
            : t('log.oldSimCleared'),
        )
      }
      addLog(t('log.engineStarted'))
      if (res.data.process_pid) {
        addLog(`  ├─ PID: ${res.data.process_pid}`)
      }
      if (res.data.engine === 'gtv_dual' || res.data.engine === 'gtv_forecast' || isGtvMode.value) {
        addLog('  ├─ 引擎: gtv_dual（Agent 过程 + 统计对照）')
      }
      // 重新推演：以服务端清空后的 sidecar 为准（空时间线），勿保留旧事件
      if (force && isGtvMode.value) {
        dealTimeline.value = res.data.deal_timeline || { events: [], event_count: 0 }
        scenarioScores.value = res.data.scenario_scores ?? null
        agentStatus.value = res.data.agent_status || null
        syncGtvTimelineActions()
      } else {
        if (res.data.deal_timeline) {
          dealTimeline.value = res.data.deal_timeline
        }
        if (res.data.scenario_scores) {
          scenarioScores.value = res.data.scenario_scores
        }
        if (res.data.agent_status) {
          agentStatus.value = res.data.agent_status
        }
        if (isGtvMode.value) syncGtvTimelineActions()
      }

      runStatus.value = res.data
      // 双轨：running 时进入轮询；仅终态才收口
      if (isDecisionComplete(res.data)) {
        phase.value = 2
        emit('update-status', 'completed')
        await refreshGtvSidecars()
        await fetchRunStatus()
        return
      }

      phase.value = 1
      startStatusPolling()
      startDetailPolling()
      if (isGtvMode.value) {
        startGtvSidecarPolling()
      }
    } else {
      startError.value = res.error || '启动失败'
      addLog(t('log.startFailed', { error: res.error || t('common.unknownError') }))
      emit('update-status', 'error')
    }
  } catch (err) {
    // 若服务端仍在 running，附着而非报死
    try {
      const detail = await getDecision(workflowId.value).catch(() => null)
      const st = String(detail?.data?.status || detail?.data?.decision?.status || '').toLowerCase()
      if (st === 'running') {
        addLog('启动请求异常，但任务仍在推演，改为附着…')
        await attachRunningSimulation()
        return
      }
    } catch (_) {
      /* fall through */
    }
    startError.value = err.message
    addLog(t('log.startException', { error: err.message }))
    emit('update-status', 'error')
  } finally {
    isStarting.value = false
  }
}

const handleRestartAll = async () => {
  if (isStarting.value || isStopping.value) return
  await doStartSimulation({ force: true, scope: 'all' })
}

const handleRestartSelectedRun = async () => {
  if (isStarting.value || isStopping.value) return
  if (!selectedSimId.value && !selectedRunId.value) {
    addLog('请先在矩阵中选中一个 Run')
    return
  }
  await doStartSimulation({ force: true, scope: 'run' })
}

// 停止模拟
const handleStopSimulation = async () => {
  if (!workflowId.value) return
  
  isStopping.value = true
  addLog(t('log.stoppingSim'))
  
  try {
    const res = await stopSimulation({ simulation_id: workflowId.value })
    
    if (res.success) {
      addLog(t('log.simStoppedSuccess'))
      phase.value = 2
      stopPolling()
      emit('update-status', 'completed')
    } else {
      addLog(t('log.stopFailed', { error: res.error || t('common.unknownError') }))
    }
  } catch (err) {
    addLog(t('log.stopException', { error: err.message }))
  } finally {
    isStopping.value = false
  }
}

// 轮询状态（降级用）；正常路径仅一条 decision SSE
let statusTimer = null
let detailTimer = null
let decisionSse = null

const TERMINAL_RUN_STATUSES = new Set([
  'completed',
  'stalled',
  'failed',
  'timeout',
  'stopped',
])

/** 矩阵中优先选正在跑的 run，其次 ready/pending，最后第一个 */
const pickActiveRun = (matrix) => {
  const runs = (matrix || []).flatMap((m) => m.runs || [])
  const by = (pred) => runs.find((r) => pred(String(r?.status || '').toLowerCase()))
  return (
    by((s) => s === 'running') ||
    by((s) => s === 'pending' || s === 'ready' || s === 'created') ||
    runs[0] ||
    null
  )
}

/** 整次决策是否终态（矩阵全部结束），不是「当前选中 Run 跑完」 */
const isDecisionComplete = (data) => {
  if (!data) return false
  // GTV 双轨：决策被误标 completed 时，若 Agent 仍在跑则不算结束
  if (isGtvMode.value) {
    const ag = data.agent_status || agentStatus.value || {}
    const agSt = String(ag.status || '').toLowerCase()
    if (agSt === 'running') return false
    if (agSt === 'failed') return true
    if (agSt === 'completed') return true
    // 尚无 agent_status：仅统计出分不算整局完成
    const st = String(data.status || data.decision_status || data.decision?.status || '').toLowerCase()
    if (st === 'running') return false
    if (['failed', 'stopped', 'prepare_failed'].includes(st)) return true
    // completed 但无 agent 终态 → 仍等 sidecar（避免 R6 误显示已完成）
    if (st === 'completed' || st === 'done' || st === 'success') {
      return Boolean(data.scenario_scores || scenarioScores.value) && agSt === 'completed'
    }
    return false
  }
  const st = String(data.status || data.decision_status || data.decision?.status || '').toLowerCase()
  if (['completed', 'done', 'success', 'failed', 'stopped', 'prepare_failed'].includes(st)) {
    return true
  }
  const progress = data.progress || runProgress.value || {}
  const total = Number(progress.total || 0)
  const done = Number(progress.done || 0)
  if (total > 0 && done >= total) return true
  const matrix = data.matrix || runMatrix.value || []
  const runs = matrix.flatMap((m) => m.runs || [])
  if (!runs.length) return false
  return runs.every((r) => TERMINAL_RUN_STATUSES.has(String(r.status || '').toLowerCase()))
}

const isRunTerminal = (data) => isDecisionComplete(data)

const applyDecisionProgressFrame = (data) => {
  if (!data) return
  applyRunStatus(data)
  const list = data.actions || data.artifacts?.actions || []
  if (Array.isArray(list) && list.length) {
    mergeActions(list)
  }
}

const startStatusPolling = () => {
  stopStatusSse()
  if (statusTimer) {
    clearInterval(statusTimer)
    statusTimer = null
  }
  if (detailTimer) {
    clearInterval(detailTimer)
    detailTimer = null
  }

  const id = workflowId.value
  if (!id) return

  // 唯一主通道：decision SSE 同帧带平台进度 + actions
  decisionSse = subscribeDecision(
    id,
    {
      onOpen: () => {
        if (statusTimer) {
          clearInterval(statusTimer)
          statusTimer = null
        }
        fetchRunStatus()
      },
      onEvent: (data) => {
        applyDecisionProgressFrame(data)
      },
      onDone: async (data) => {
        applyDecisionProgressFrame(data)
        decisionSse = null
        // 决策未终态时必须降级轮询（防止误关流后 UI 冻住）
        if (!isDecisionComplete(data || runStatus.value) && phase.value === 1 && !statusTimer) {
          statusTimer = setInterval(async () => {
            await fetchRunStatus()
            await fetchRunStatusDetail()
          }, 3000)
        }
      },
      onError: (err) => {
        console.warn('[SandOwl] decision SSE error, fallback poll', err)
        if (!statusTimer && phase.value === 1 && !isDecisionComplete(runStatus.value)) {
          statusTimer = setInterval(async () => {
            await fetchRunStatus()
            await fetchRunStatusDetail()
          }, 3000)
        }
      },
    },
    {
      simId: selectedSimId.value || undefined,
      actionsFrom: allActions.value.length,
    },
  )
}

const mergeActions = (serverActions = []) => {
  let newActionsAdded = 0
  serverActions.forEach((action) => {
    const t = String(action.action_type || '').toUpperCase()
    const args = action.action_args || {}
    const content =
      action.content || args.content || args.quote_content || args.post_content || ''
    if (t === 'LLM_ACTION' && !String(content).trim()) return

    const actionId =
      action.id ||
      (action._rowid != null ? `${action.platform}:${action._rowid}` : null) ||
      `${action.timestamp || action.round}-${action.platform}-${action.agent_id}-${action.action_type}-${String(content).slice(0, 24)}`

    if (!actionIds.value.has(actionId)) {
      actionIds.value.add(actionId)
      allActions.value.push({
        ...action,
        action_args: {
          ...args,
          ...(content && !args.content ? { content } : {}),
        },
        _uniqueId: actionId,
      })
      newActionsAdded++
    }
  })
  return newActionsAdded
}

/** 兼容旧调用：详情走同通道降级拉取，不再开第二条 SSE */
const startDetailPolling = () => {
  // 首包补齐动作；后续由 decision SSE 同帧推送
  fetchRunStatusDetail()
}

const stopStatusSse = () => {
  if (decisionSse) {
    try {
      decisionSse.close()
    } catch (_) {
      /* ignore */
    }
    decisionSse = null
  }
}

const stopPolling = () => {
  if (statusTimer) {
    clearInterval(statusTimer)
    statusTimer = null
  }
  if (detailTimer) {
    clearInterval(detailTimer)
    detailTimer = null
  }
  stopStatusSse()
  stopGtvSidecarPolling()
}

// 追踪各平台的上一次轮次，用于检测变化并输出日志
const prevTwitterRound = ref(0)
const prevRedditRound = ref(0)

const onSelectRun = (row) => {
  userPinnedRun.value = true
  selectedRunId.value = row.run_id
  selectedSimId.value = row.sim_id
  // 切换 Run 时清空时间线，避免混入其他方案动作
  allActions.value = []
  actionIds.value = new Set()
  addLog(`查看 Run ${row.run_id} / ${row.sim_id || ''}（仅切换检视，不影响推演范围）`)
  if (phase.value === 1) {
    startStatusPolling()
    fetchRunStatusDetail()
  } else {
    fetchRunStatus()
    fetchRunStatusDetail()
  }
}

/** 取消钉住，回到当前进行中的 Run */
const followLiveRun = () => {
  userPinnedRun.value = false
  const next = pickActiveRun(runMatrix.value)
  if (!next?.sim_id) return
  if (next.sim_id === selectedSimId.value && next.run_id === selectedRunId.value) {
    addLog('已在跟随进行中的 Run')
    return
  }
  selectedRunId.value = next.run_id
  selectedSimId.value = next.sim_id
  allActions.value = []
  actionIds.value = new Set()
  addLog(`跟随进行中：${next.run_id}`)
  if (phase.value === 1) {
    startStatusPolling()
  }
  fetchRunStatus()
  fetchRunStatusDetail()
}

function emitStatusLabel(data) {
  // 决策已终态时不要把顶栏打回 processing（切 Run / 重拉快照会误触发）
  if (phase.value === 2 || isDecisionComplete(data)) {
    emit('update-status', { status: 'completed' })
    return
  }
  if (phase.value === 0 && !isStarting.value) return

  const cur = Math.max(
    Number(data?.twitter_current_round || 0),
    Number(data?.reddit_current_round || 0),
  )
  const tot = Number(data?.total_rounds || 0)
  let scenarioName = ''
  for (const sc of runMatrix.value || []) {
    const hit = (sc.runs || []).find(
      (r) => r.run_id === selectedRunId.value || r.sim_id === selectedSimId.value,
    )
    if (hit) {
      scenarioName = sc.scenario_name || sc.kind || ''
      break
    }
  }
  if (!scenarioName) scenarioName = t('common.running')
  if (tot > 0) {
    emit('update-status', {
      status: 'processing',
      text: t('step3.statusRunningRound', {
        scenario: scenarioName,
        current: cur,
        total: tot,
      }),
    })
  } else {
    emit('update-status', { status: 'processing', text: scenarioName })
  }
}

const applyRunStatus = (data) => {
  if (!data) return

  const prevSim = selectedSimId.value
  if (data.matrix) {
    runMatrix.value = data.matrix
    runProgress.value = data.progress || { done: 0, total: 0 }
    if (!selectedRunId.value) {
      const pick = pickActiveRun(data.matrix)
      if (pick) {
        selectedRunId.value = pick.run_id
        selectedSimId.value = pick.sim_id || data.sim_id || selectedSimId.value
      } else if (data.sim_id) {
        selectedSimId.value = data.sim_id
      }
    } else if (!selectedSimId.value && data.sim_id) {
      selectedSimId.value = data.sim_id
    }
  }

  runStatus.value = data

  // 卡片 ACTS 与时间线同源：若 run_state 计数为 0 但已有动作，用本地计数回填
  if (allActions.value.length > 0) {
    const tw = allActions.value.filter((a) => a.platform !== 'reddit').length
    const rd = allActions.value.filter((a) => a.platform === 'reddit').length
    if (!(data.twitter_actions_count > 0) && tw > 0) {
      runStatus.value = { ...runStatus.value, twitter_actions_count: tw }
    }
    if (!(data.reddit_actions_count > 0) && rd > 0) {
      runStatus.value = { ...runStatus.value, reddit_actions_count: rd }
    }
  }

  // selectedSimId 首次确定：重订同 URL（带 sim_id），仍是一条 SSE
  if (!prevSim && selectedSimId.value && phase.value === 1) {
    startStatusPolling()
  }

  if (data.twitter_current_round > prevTwitterRound.value) {
    addLog(`[Plaza] R${data.twitter_current_round}/${data.total_rounds} | T:${data.twitter_simulated_hours || 0}h | A:${data.twitter_actions_count}`)
    prevTwitterRound.value = data.twitter_current_round
  }

  if (data.reddit_current_round > prevRedditRound.value) {
    addLog(`[Community] R${data.reddit_current_round}/${data.total_rounds} | T:${data.reddit_simulated_hours || 0}h | A:${data.reddit_actions_count}`)
    prevRedditRound.value = data.reddit_current_round
  }

  // 顶栏：方案名 · Rk/n
  emitStatusLabel(data)

  const decisionDone = isDecisionComplete(data)
  const selectedRunDone =
    ['completed', 'stopped', 'failed'].includes(String(data.runner_status || '').toLowerCase()) ||
    checkPlatformsCompleted(data)

  // 当前 Run 结束但决策未完：未手动钉住时自动切到下一个 running/ready，并保持 SSE
  if (!decisionDone && selectedRunDone && phase.value === 1 && !userPinnedRun.value) {
    const next = pickActiveRun(data.matrix || runMatrix.value)
    if (next?.sim_id && next.sim_id !== selectedSimId.value) {
      selectedRunId.value = next.run_id
      selectedSimId.value = next.sim_id
      allActions.value = []
      actionIds.value = new Set()
      addLog(`当前 Run 已结束，切换到 ${next.run_id}`)
      startStatusPolling()
      fetchRunStatusDetail()
    }
    return
  }

  if (decisionDone) {
    if (checkPlatformsCompleted(data) && String(data.status || '').toLowerCase() !== 'completed') {
      addLog(t('log.allPlatformsCompleted'))
    }
    addLog(t('log.simCompleted'))
    phase.value = 2
    stopPolling()
    stopGtvSidecarPolling()
    emit('update-status', { status: 'completed' })
    const decId = props.decisionId || (
      String(props.simulationId || '').startsWith('dec_') ? props.simulationId : ''
    )
    if (decId && String(decId).startsWith('dec_')) {
      syncWorkflowFromServer(decId)
    }
    if (isGtvMode.value) refreshGtvSidecars()
  }
}

const fetchRunStatus = async () => {
  if (!workflowId.value) return
  
  try {
    const res = await getRunStatus(workflowId.value, {
      selectedSimId: selectedSimId.value || undefined,
    })
    
    if (res.success && res.data) {
      applyRunStatus(res.data)
    }
  } catch (err) {
    console.warn('获取运行状态失败:', err)
  }
}

// 检查所有启用的平台是否已完成
const checkPlatformsCompleted = (data) => {
  // 如果没有任何平台数据，返回 false
  if (!data) return false

  // GTV 双轨无社媒平台：以决策 status / run_state 完成标记为准
  if (isGtvMode.value) {
    return (
      data.twitter_completed === true ||
      data.reddit_completed === true ||
      ['completed', 'done', 'success'].includes(String(data.status || '').toLowerCase())
    )
  }

  // 检查各平台的完成状态
  const twitterCompleted = data.twitter_completed === true
  const redditCompleted = data.reddit_completed === true

  // 如果至少有一个平台完成了，检查是否所有启用的平台都完成了
  // 通过 actions_count 判断平台是否被启用（如果 count > 0 或 running 曾为 true）
  const twitterEnabled = (data.twitter_actions_count > 0) || data.twitter_running || twitterCompleted
  const redditEnabled = (data.reddit_actions_count > 0) || data.reddit_running || redditCompleted

  // 如果没有任何平台被启用，返回 false
  if (!twitterEnabled && !redditEnabled) return false

  // 检查所有启用的平台是否都已完成
  if (twitterEnabled && !twitterCompleted) return false
  if (redditEnabled && !redditCompleted) return false

  return true
}

let gtvSidecarTimer = null
const refreshGtvSidecars = async () => {
  if (!workflowId.value || !isGtvMode.value) return
  try {
    const detail = await getDecision(workflowId.value).catch(() => null)
    const payload = detail?.data || {}
    if (payload.deal_timeline) {
      dealTimeline.value = payload.deal_timeline
    }
    // 允许 null：重新推演清空后要丢掉旧统计事件
    if (Object.prototype.hasOwnProperty.call(payload, 'scenario_scores')) {
      scenarioScores.value = payload.scenario_scores
    }
    if (payload.agent_status) agentStatus.value = payload.agent_status
    const cur = Number(payload.current_round ?? payload.agent_status?.current_round)
    const tot = Number(payload.total_rounds ?? payload.agent_status?.total_rounds)
    if (!Number.isNaN(cur) && cur >= 0) {
      runStatus.value = {
        ...runStatus.value,
        current_round: cur,
        total_rounds: !Number.isNaN(tot) && tot > 0 ? tot : runStatus.value.total_rounds || 16,
        twitter_current_round: cur,
        reddit_current_round: cur,
        status: payload.status || payload.decision?.status || runStatus.value.status,
      }
    }
    syncGtvTimelineActions()
  } catch (e) {
    console.warn('GTV sidecar refresh failed', e)
  }
}
const startGtvSidecarPolling = () => {
  stopGtvSidecarPolling()
  refreshGtvSidecars()
  gtvSidecarTimer = setInterval(refreshGtvSidecars, 2000)
}
const stopGtvSidecarPolling = () => {
  if (gtvSidecarTimer) {
    clearInterval(gtvSidecarTimer)
    gtvSidecarTimer = null
  }
}

const fetchRunStatusDetail = async () => {
  if (!workflowId.value) return

  try {
    const res = await getRunStatusDetail(workflowId.value, {
      simId: selectedSimId.value || undefined,
    })

    if (res.success && res.data) {
      mergeActions(res.data.all_actions || [])
    }
  } catch (err) {
    console.warn('获取详细状态失败:', err)
  }
}

// Helpers
const getActionTypeLabel = (type) => {
  const labels = {
    'CREATE_POST': 'POST',
    'REPOST': 'REPOST',
    'LIKE_POST': 'LIKE',
    'DISLIKE_POST': 'DISLIKE',
    'CREATE_COMMENT': 'COMMENT',
    'LIKE_COMMENT': 'LIKE',
    'DO_NOTHING': 'IDLE',
    'FOLLOW': 'FOLLOW',
    'SEARCH_POSTS': 'SEARCH',
    'QUOTE_POST': 'QUOTE',
    'UPVOTE_POST': 'UPVOTE',
    'DOWNVOTE_POST': 'DOWNVOTE',
    'LLM_ACTION': 'ACTION',
    'DEAL_ACTION': 'DEAL',
    'STAT_SCORE': 'SCORE',
  }
  return labels[type] || type || 'UNKNOWN'
}

const getActionTypeClass = (type) => {
  const classes = {
    'CREATE_POST': 'badge-post',
    'REPOST': 'badge-action',
    'LIKE_POST': 'badge-action',
    'CREATE_COMMENT': 'badge-comment',
    'LIKE_COMMENT': 'badge-action',
    'QUOTE_POST': 'badge-post',
    'FOLLOW': 'badge-meta',
    'SEARCH_POSTS': 'badge-meta',
    'UPVOTE_POST': 'badge-action',
    'DOWNVOTE_POST': 'badge-action',
    'DO_NOTHING': 'badge-idle',
    'DEAL_ACTION': 'badge-post',
    'STAT_SCORE': 'badge-meta',
  }
  return classes[type] || 'badge-default'
}

/** 将 GTV Agent sidecar 写入时间线（统计轨不进时间线，走上方 KPI/榜单面板） */
const syncGtvTimelineActions = () => {
  if (!isGtvMode.value) return

  // 清掉历史误写入的 stat 伪事件
  const kept = allActions.value.filter(
    (a) => a.platform !== 'agent' && a.platform !== 'stat',
  )
  const next = [...kept]
  const nextIds = new Set(kept.map((a) => a._uniqueId).filter(Boolean))
  const push = (action) => {
    const actionId = action._uniqueId
    if (!actionId || nextIds.has(actionId)) return false
    nextIds.add(actionId)
    next.push(action)
    return true
  }

  const events = dealTimeline.value?.events || []
  events.forEach((ev, idx) => {
    const rid = ev.round ?? ev.day ?? 0
    const actionId = `gtv-agent:${rid}:${ev.thread_id || ''}:${ev.action || ''}:${idx}:${String(ev.text || '').slice(0, 48)}`
    push({
      _uniqueId: actionId,
      platform: 'agent',
      action_type: 'DEAL_ACTION',
      agent_name: ev.broker_name || ev.broker || ev.actor || '成交 Agent',
      agent_id: ev.broker_id || ev.thread_id || ev.listing_id || `T${idx}`,
      round_num: rid,
      timestamp: ev.ts || dealTimeline.value?.generated_at || new Date().toISOString(),
      action_args: {
        content: ev.text || `${ev.stage_label || ev.stage || '动作'}`,
        stage: ev.stage,
        stage_label: ev.stage_label || ev.stage || '动作',
        from_stage: ev.from_stage,
        from_stage_label: ev.from_stage_label || ev.from_stage || '',
        city: ev.city,
        address: ev.address || '',
        amap_address: ev.amap_address || '',
        longitude: ev.longitude,
        latitude: ev.latitude,
        quality_score: ev.quality_score,
        quality_highlights: ev.quality_highlights || '',
        listing_id: ev.listing_id,
        listing_name: ev.listing_name || '',
        listing_type: ev.listing_type || '',
        listing_label: ev.listing_label || '',
        broker_id: ev.broker_id || '',
        broker_name: ev.broker_name || ev.broker || '',
        broker_label: ev.broker_label || '',
        path: ev.path || '',
      },
    })
  })

  if (agentTrackFailed.value) {
    const msg =
      agentStatus.value?.message ||
      agentStatus.value?.error ||
      '成交 Agent 轨不可用（通常因未配置 LLM）；统计轨仍可在上方面板对照。'
    push({
      _uniqueId: 'gtv-agent:failed',
      platform: 'agent',
      action_type: 'DEAL_ACTION',
      agent_name: '成交 Agent',
      round_num: 0,
      timestamp: new Date().toISOString(),
      action_args: {
        content: msg,
        stage_label: '不可用',
      },
    })
  }

  const prevLen = allActions.value.length
  allActions.value = next
  actionIds.value = nextIds
  if (next.length !== prevLen || next.length > kept.length) {
    nextTick(scrollTimelineToBottom)
  }
}

const truncateContent = (content, maxLength = 100) => {
  if (!content) return ''
  if (content.length > maxLength) return content.substring(0, maxLength) + '...'
  return content
}

const formatActionTime = (timestamp) => {
  if (!timestamp) return ''
  try {
    return new Date(timestamp).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

const handleNextStep = async () => {
  if (!workflowId.value) {
    addLog(t('log.errorMissingSimId'))
    return
  }

  if (isGeneratingReport.value) {
    addLog(t('log.reportRequestSent'))
    return
  }
  
  isGeneratingReport.value = true
  addLog(t('log.startingReportGen'))
  
  try {
    const res = await generateReport({
      simulation_id: workflowId.value,
      force_regenerate: true
    })
    
    if (res.success && res.data) {
      const reportId = res.data.report_id
      const reportTaskId = res.data.task_id
      if (reportId && reportTaskId && String(reportTaskId).startsWith('task_')) {
        try {
          sessionStorage.setItem(`adc_report_task_${reportId}`, reportTaskId)
          const decisionId = workflowId.value
          if (decisionId && decisionId !== reportId) {
            sessionStorage.setItem(`adc_report_task_${decisionId}`, reportTaskId)
          }
        } catch (_) {
          /* ignore */
        }
      }
      addLog(t('log.reportGenTaskStarted', { reportId }))
      const decisionId = workflowId.value
      const patch = { decisionId }
      if (String(reportId || '').startsWith('report_')) patch.reportId = reportId
      touchWorkflowStep(4, patch)
      // 跳转到报告页面：地址栏始终用 decisionId
      router.push(taskRoute(4, decisionId))
    } else {
      addLog(t('log.reportGenFailed', { error: res.error || t('common.unknownError') }))
      isGeneratingReport.value = false
    }
  } catch (err) {
    addLog(t('log.reportGenException', { error: err.message }))
    isGeneratingReport.value = false
  }
}

function onTimelineScroll() {
  const el = scrollContainer.value
  if (!el) return
  const dist = el.scrollHeight - el.scrollTop - el.clientHeight
  stickTimelineToBottom.value = dist <= TIMELINE_BOTTOM_THRESHOLD
}

function scrollTimelineToBottom() {
  const el = scrollContainer.value
  if (!el || !stickTimelineToBottom.value) return
  el.scrollTop = el.scrollHeight
}

watch(
  () => allActions.value.length,
  () => {
    nextTick(scrollTimelineToBottom)
  },
)

onMounted(async () => {
  addLog(t('log.step3Init'))
  if (!workflowId.value) return

  try {
    const detail = await getDecision(workflowId.value).catch(() => null)
    const payload = detail?.data || {}
    sceneTemplate.value = String(
      payload.template || payload.decision?.template || '',
    ).toLowerCase()
    if (payload.deal_timeline) {
      dealTimeline.value = payload.deal_timeline
    }
    if (payload.scenario_scores) scenarioScores.value = payload.scenario_scores
    if (payload.agent_status) agentStatus.value = payload.agent_status
    if (isGtvMode.value) {
      addLog('商业模板 gtv_deal：双轨推演（Agent 时间线 + 统计 KPI/榜单）')
      syncGtvTimelineActions()
    }
    const status = String(payload.status || payload.decision?.status || '').toLowerCase()

    if (['completed', 'done', 'success'].includes(status)) {
      await attachRunningSimulation({ completed: true })
      return
    }
    if (['failed', 'stopped', 'error'].includes(status)) {
      await attachRunningSimulation({ completed: true })
      addLog(`任务状态 ${status}，可点「重新推演」重开`)
      return
    }
    if (status === 'running') {
      // 若 env 仍活或矩阵有 running run → attach；否则视为僵尸，允许非 force 启动
      let envAlive = false
      try {
        const env = await getEnvStatus({ simulation_id: workflowId.value })
        envAlive = Boolean(env?.data?.env_alive)
      } catch (_) {
        /* ignore */
      }
      const hasRunningRun = (payload.matrix || []).some((m) =>
        (m.runs || []).some((r) => String(r.status || '').toLowerCase() === 'running'),
      )
      if (envAlive || hasRunningRun || isGtvMode.value) {
        await attachRunningSimulation()
        if (isGtvMode.value) startGtvSidecarPolling()
        return
      }
      addLog('决策标记 running 但进程未存活，重新启动推演…')
      await doStartSimulation({ force: false })
      return
    }

    // prepared / created / 其它：首次进入，非 force 启动
    await doStartSimulation({ force: false })
  } catch (err) {
    addLog(`初始化推演页失败: ${err.message || err}`)
    await doStartSimulation({ force: false })
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.simulation-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #FFFFFF;
  font-family: var(--font-sans);
  overflow: hidden;
  min-height: 0;
}

/* --- Decision bar（推演全部） --- */
.decision-bar {
  background: #FFF;
  padding: 10px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid #EAEAEA;
  z-index: 10;
  flex: 0 0 auto;
  flex-wrap: wrap;
  min-height: 48px;
}

.decision-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.decision-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: #111;
}

.decision-progress {
  font-size: 12px;
  padding: 2px 8px;
  border: 1px solid #EAEAEA;
  background: #FAFAFA;
  color: #333;
}

.decision-phase {
  font-size: 11px;
  font-weight: 600;
  color: #888;
}

.decision-phase.is-running {
  color: #e65100;
}

.gtv-progress {
  margin: 12px 16px 16px;
  padding: 14px 16px;
  border: 1px solid #e5e5e5;
  background: #fafafa;
}

.gtv-progress-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 0.85rem;
  font-weight: 600;
}

.gtv-badge {
  font-family: var(--font-mono);
  font-size: 0.72rem;
  font-weight: 500;
  color: #666;
}

.gtv-badge.is-running {
  color: #c45c26;
}

.gtv-badge.is-done {
  color: #1f7a4c;
}

.gtv-progress-desc {
  margin: 0 0 12px;
  font-size: 0.82rem;
  line-height: 1.5;
  color: #666;
}

.gtv-progress-bar {
  height: 6px;
  background: #eaeaea;
  overflow: hidden;
}

.gtv-progress-fill {
  height: 100%;
  background: #1a1a1a;
  transition: width 0.35s ease-out;
}

.gtv-progress-meta {
  margin-top: 8px;
  font-size: 0.72rem;
  color: #888;
}
.gtv-round-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  margin-bottom: 10px;
  font-size: 0.78rem;
  color: #444;
}
.gtv-agent-msg {
  color: #888;
  font-weight: 400;
}

/* GTV 统计轨：KPI + 榜单（非时间线） */
.gtv-stat-panel {
  margin: 0 16px 8px;
  padding: 14px 16px 16px;
  border: 1px solid #e5e5e5;
  background: #fafafa;
}
.gtv-stat-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.gtv-stat-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #222;
}
.gtv-stat-sub {
  font-size: 0.75rem;
  font-weight: 400;
  color: #777;
}
.gtv-stat-mode {
  flex: 0 0 auto;
  font-size: 0.72rem;
  color: #1f7a4c;
  padding-top: 2px;
}
.gtv-stat-mode.is-wait {
  color: #c45c26;
}
.gtv-stat-empty {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 8px 0 4px;
}
.gtv-stat-empty p {
  margin: 0;
  font-size: 0.8rem;
  color: #666;
  line-height: 1.45;
}
.gtv-stat-skel {
  height: 6px;
  width: min(240px, 60%);
  background: linear-gradient(90deg, #ececec 0%, #f5f5f5 45%, #ececec 100%);
  background-size: 200% 100%;
  animation: gtv-skel 1.2s ease-out infinite;
}
@keyframes gtv-skel {
  0% { background-position: 100% 0; }
  100% { background-position: -100% 0; }
}
.gtv-stat-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}
.gtv-stat-tab {
  border: 1px solid #ddd;
  background: #fff;
  color: #444;
  font-size: 0.75rem;
  padding: 5px 10px;
  cursor: pointer;
  transition: background 0.15s ease-out, border-color 0.15s ease-out, color 0.15s ease-out;
}
.gtv-stat-tab:hover {
  border-color: #bbb;
  background: #f7f7f7;
}
.gtv-stat-tab.active {
  background: #111;
  border-color: #111;
  color: #fff;
}
.gtv-stat-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.gtv-kpi {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 8px 0;
  border-top: 1px solid #e8e8e8;
}
.gtv-kpi-label {
  font-size: 0.72rem;
  color: #888;
  font-weight: 600;
}
.gtv-kpi-val {
  font-size: 1rem;
  color: #111;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.gtv-kpi-val.is-up { color: #1f7a4c; }
.gtv-kpi-val.is-down { color: #b42318; }
.gtv-stat-boards {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
  gap: 14px;
}
.gtv-board-head {
  font-size: 0.72rem;
  font-weight: 600;
  color: #555;
  margin-bottom: 8px;
  letter-spacing: 0.02em;
}
.gtv-board-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.76rem;
  background: #fff;
}
.gtv-board-table th,
.gtv-board-table td {
  text-align: left;
  padding: 7px 8px;
  border-bottom: 1px solid #eee;
  vertical-align: top;
}
.gtv-board-table th {
  color: #888;
  font-weight: 600;
  font-size: 0.7rem;
  background: #f3f3f3;
}
.gtv-board-table tbody tr:hover td {
  background: #fafafa;
}
.gtv-board-name {
  color: #222;
  font-weight: 500;
  line-height: 1.35;
}
.gtv-board-id {
  margin-top: 2px;
  font-size: 0.68rem;
  color: #999;
  word-break: break-all;
}
.gtv-board-addr {
  margin-top: 2px;
  font-size: 0.7rem;
  color: #777;
  line-height: 1.35;
}
.gtv-board-empty {
  margin: 0;
  font-size: 0.78rem;
  color: #888;
  padding: 10px 0;
}
@media (max-width: 900px) {
  .gtv-stat-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .gtv-stat-boards {
    grid-template-columns: 1fr;
  }
}
@media (prefers-reduced-motion: reduce) {
  .gtv-stat-skel { animation: none; }
}

.decision-phase.is-done {
  color: #1a936f;
}

/* --- Run inspector --- */
.run-inspector {
  flex: 0 0 auto;
  border-bottom: 1px solid #EAEAEA;
  background: #FFF;
}

.inspector-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 16px 0;
}

.inspector-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.inspector-kicker {
  font-size: 11px;
  font-weight: 600;
  color: #999;
  letter-spacing: 0.04em;
}

.inspector-name {
  font-size: 13px;
  font-weight: 700;
  color: #111;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inspector-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.follow-live-btn {
  flex-shrink: 0;
  border: 1px solid #ccc;
  background: #fff;
  color: #333;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  cursor: pointer;
  border-radius: 3px;
}

.follow-live-btn:hover:not(:disabled) {
  background: #f5f5f5;
  border-color: #999;
}

.follow-live-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.platform-row {
  display: flex;
  gap: 8px;
  padding: 8px 16px 10px;
  flex-wrap: wrap;
  min-width: 0;
}

/* Platform Status Cards */
.platform-status {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 5px 10px;
  border-radius: 4px;
  background: #FAFAFA;
  border: 1px solid #EAEAEA;
  opacity: 0.7;
  transition: all 0.3s;
  min-width: 128px;
  position: relative;
  cursor: pointer;
}

.platform-status.active {
  opacity: 1;
  border-color: #333;
  background: #FFF;
}

.platform-status.completed {
  opacity: 1;
  border-color: #1A936F;
  background: #F2FAF6;
}

/* Actions Tooltip */
.actions-tooltip {
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  margin-top: 8px;
  padding: 10px 14px;
  background: #000;
  color: #FFF;
  border-radius: 4px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  opacity: 0;
  visibility: hidden;
  transition: all 0.2s ease;
  z-index: 100;
  min-width: 180px;
  pointer-events: none;
}

.actions-tooltip::before {
  content: '';
  position: absolute;
  top: -6px;
  left: 50%;
  transform: translateX(-50%);
  border-left: 6px solid transparent;
  border-right: 6px solid transparent;
  border-bottom: 6px solid #000;
}

.platform-status:hover .actions-tooltip {
  opacity: 1;
  visibility: visible;
}

.tooltip-title {
  font-size: 10px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 8px;
}

.tooltip-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tooltip-action {
  font-size: 10px;
  font-weight: 600;
  padding: 3px 8px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 2px;
  color: #FFF;
  letter-spacing: 0.03em;
}

.platform-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 2px;
}

.platform-name {
  font-size: 11px;
  font-weight: 700;
  color: #000;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.platform-status.twitter .platform-icon { color: #000; }
.platform-status.reddit .platform-icon { color: #000; }

.platform-stats {
  display: flex;
  gap: 10px;
}

.stat {
  display: flex;
  align-items: baseline;
  gap: 3px;
}

.stat-label {
  font-size: 8px;
  color: #999;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.stat-value {
  font-size: 11px;
  font-weight: 600;
  color: #333;
}

.stat-total, .stat-unit {
  font-size: 9px;
  color: #999;
  font-weight: 400;
}

.status-badge {
  margin-left: auto;
  color: #1A936F;
  display: flex;
  align-items: center;
}

/* Action Button */
.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 600;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s ease;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.action-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  margin-left: auto;
}

.action-btn.danger {
  background: #fff;
  color: #c0392b;
  border: 1px solid #c0392b;
}

.action-btn.danger:hover:not(:disabled) {
  background: #c0392b;
  color: #fff;
}

.action-btn.danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-btn.secondary {
  background: #fff;
  color: #333;
  border: 1px solid #ccc;
  white-space: nowrap;
}

.action-btn.secondary:hover:not(:disabled) {
  background: #f5f5f5;
}

.action-btn.primary {
  background: #000;
  color: #FFF;
  white-space: nowrap;
}

.action-btn.primary:hover:not(:disabled) {
  background: #333;
}

.action-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* --- Main Content Area --- */
.main-content-area {
  flex: 1 1 auto;
  overflow-y: auto;
  position: relative;
  background: #FFF;
  min-height: 0;
}

/* Timeline Header */
.timeline-header {
  position: sticky;
  top: 0;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(8px);
  padding: 12px 24px;
  border-bottom: 1px solid #EAEAEA;
  z-index: 5;
  display: flex;
  justify-content: center;
}

.timeline-stats {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 11px;
  color: #666;
  background: #F5F5F5;
  padding: 4px 12px;
  border-radius: 20px;
}

.total-count {
  font-weight: 600;
  color: #333;
}

.platform-breakdown {
  display: flex;
  align-items: center;
  gap: 8px;
}

.breakdown-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.breakdown-divider { color: #DDD; }
.breakdown-item.twitter { color: #000; }
.breakdown-item.reddit { color: #000; }

/* --- Timeline Feed --- */
.timeline-feed {
  padding: 24px 0;
  position: relative;
  min-height: 100%;
  max-width: 900px;
  margin: 0 auto;
}

/* GTV：Agent 单轨时间线（不再左右对开） */
.timeline-feed.gtv-agent-feed {
  max-width: 760px;
  margin: 0;
  padding-left: 16px;
  padding-right: 24px;
}
.timeline-feed.gtv-agent-feed .timeline-axis {
  left: 22px;
  transform: none;
}
.timeline-feed.gtv-agent-feed .timeline-marker {
  left: 22px;
}
.timeline-feed.gtv-agent-feed .timeline-item.agent {
  justify-content: flex-start;
  padding-right: 0;
  padding-left: 40px;
}
.timeline-feed.gtv-agent-feed .timeline-item.agent .timeline-card {
  width: 100%;
  margin-left: 0;
  margin-right: 0;
}

.timeline-axis {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 1px;
  background: #EAEAEA; /* Cleaner line */
  transform: translateX(-50%);
}

.timeline-item {
  display: flex;
  justify-content: center;
  margin-bottom: 32px;
  position: relative;
  width: 100%;
}

.timeline-marker {
  position: absolute;
  left: 50%;
  top: 24px;
  width: 10px;
  height: 10px;
  background: #FFF;
  border: 1px solid #CCC;
  border-radius: 50%;
  transform: translateX(-50%);
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
}

.marker-dot {
  width: 4px;
  height: 4px;
  background: #CCC;
  border-radius: 50%;
}

.timeline-item.twitter .marker-dot,
.timeline-item.agent .marker-dot { background: #000; }
.timeline-item.reddit .marker-dot,
.timeline-item.stat .marker-dot { background: #000; }
.timeline-item.twitter .timeline-marker,
.timeline-item.agent .timeline-marker { border-color: #000; }
.timeline-item.reddit .timeline-marker,
.timeline-item.stat .timeline-marker { border-color: #000; }

/* Card Layout */
.timeline-card {
  width: calc(100% - 48px);
  background: #FFF;
  border-radius: 2px;
  padding: 16px 20px;
  border: 1px solid #EAEAEA;
  box-shadow: 0 2px 10px rgba(0,0,0,0.02);
  position: relative;
  transition: all 0.2s;
}

.timeline-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.05);
  border-color: #DDD;
}

/* Left side (Twitter / GTV Agent) */
.timeline-item.twitter,
.timeline-item.agent {
  justify-content: flex-start;
  padding-right: 50%;
}
.timeline-item.twitter .timeline-card,
.timeline-item.agent .timeline-card {
  margin-left: auto;
  margin-right: 32px; /* Gap from axis */
}

/* Right side (Reddit / GTV 统计) */
.timeline-item.reddit,
.timeline-item.stat {
  justify-content: flex-end;
  padding-left: 50%;
}
.timeline-item.reddit .timeline-card,
.timeline-item.stat .timeline-card {
  margin-right: auto;
  margin-left: 32px; /* Gap from axis */
}

.gtv-track-tag {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #555;
}

.gtv-entity-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
  padding: 8px 10px;
  background: #f7f7f7;
  border: 1px solid #ececec;
  font-size: 0.78rem;
  line-height: 1.45;
}

.gtv-entity-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 10px;
}

.gtv-entity-k {
  flex: 0 0 auto;
  color: #888;
  font-weight: 600;
  min-width: 3em;
}

.gtv-entity-v {
  color: #222;
  font-weight: 600;
  max-width: 36ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gtv-entity-id {
  color: #666;
  font-size: 0.72rem;
  word-break: break-all;
}

.gtv-entity-from {
  color: #999;
  font-size: 0.72rem;
}

/* Card Content Styles */
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #F5F5F5;
}

.agent-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.avatar-placeholder {
  width: 24px;
  height: 24px;
  background: #000;
  color: #FFF;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}

.agent-name {
  font-size: 13px;
  font-weight: 600;
  color: #000;
}

.header-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.platform-indicator {
  color: #999;
  display: flex;
  align-items: center;
}

.action-badge {
  font-size: 9px;
  padding: 2px 6px;
  border-radius: 2px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border: 1px solid transparent;
}

/* Monochromatic Badges */
.badge-post { background: #F0F0F0; color: #333; border-color: #E0E0E0; }
.badge-comment { background: #F0F0F0; color: #666; border-color: #E0E0E0; }
.badge-action { background: #FFF; color: #666; border: 1px solid #E0E0E0; }
.badge-meta { background: #FAFAFA; color: #999; border: 1px dashed #DDD; }
.badge-idle { opacity: 0.5; }

.content-text {
  font-size: 13px;
  line-height: 1.6;
  color: #333;
  margin-bottom: 10px;
}

.content-text.main-text {
  font-size: 14px;
  color: #000;
}

/* Info Blocks (Quote, Repost, etc) */
.quoted-block, .repost-content {
  background: #F9F9F9;
  border: 1px solid #EEE;
  padding: 10px 12px;
  border-radius: 2px;
  margin-top: 8px;
  font-size: 12px;
  color: #555;
}

.quote-header, .repost-info, .like-info, .search-info, .follow-info, .vote-info, .idle-info, .comment-context {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 11px;
  color: #666;
}

.icon-small {
  color: #999;
}
.icon-small.filled {
  color: #999; /* Keep icons neutral unless highlighted */
}

.search-query {
  font-family: var(--font-mono);
  background: #F0F0F0;
  padding: 0 4px;
  border-radius: 2px;
}

.card-footer {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
  font-size: 10px;
  color: #BBB;
  font-family: var(--font-mono);
}

/* Waiting State */
.waiting-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  color: #CCC;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.pulse-ring {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid #EAEAEA;
  animation: ripple 2s infinite;
}

@keyframes ripple {
  0% { transform: scale(0.8); opacity: 1; border-color: #CCC; }
  100% { transform: scale(2.5); opacity: 0; border-color: #EAEAEA; }
}

/* Animation */
.timeline-item-enter-active,
.timeline-item-leave-active {
  transition: all 0.4s cubic-bezier(0.165, 0.84, 0.44, 1);
}

.timeline-item-enter-from {
  opacity: 0;
  transform: translateY(20px);
}

.timeline-item-leave-to {
  opacity: 0;
}

.mono { font-family: var(--font-mono); }

/* Loading spinner for button */
.loading-spinner-small {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #FFF;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-right: 6px;
}
</style>