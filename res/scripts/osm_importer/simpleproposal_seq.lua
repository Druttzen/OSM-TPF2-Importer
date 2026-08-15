local simpleproposal = require"osm_importer.simpleproposal"
local nodesheights = require"osm_importer.nodesheights"
local tools = require"osm_importer.tools"
local timer = require"osm_importer.timer"

local s = {}


local function failpct(n, d)
	if not d or d == 0 then
		return 0
	end
	return 100 * n / d
end

local function persistRemaining()
	local keys = {}
	if s.seqlist and s.seqi and s.nseq then
		for i = s.seqi, s.nseq do
			local edge = s.seqlist[i]
			if edge and edge.__key then
				keys[#keys+1] = edge.__key
			end
		end
	end
	_G.osm_importer_seq_keys = keys
end

local function restoreRemaining(data)
	local keys = _G.osm_importer_seq_keys
	if type(keys) ~= "table" or #keys == 0 then
		return nil
	end
	local list = {}
	for _, key in ipairs(keys) do
		local edge = data.edges[key]
		if edge then
			edge.__key = key
			list[#list+1] = edge
		end
	end
	if #list == 0 then
		return nil
	end
	return list
end

function s.edgeAlreadyBuilt(edge)
	local n0 = s.data.nodes[edge.node0]
	local n1 = s.data.nodes[edge.node1]
	if not n0 or not n1 then
		return false
	end
	local id0 = s.getIdIfExist(edge.node0)
	local id1 = s.getIdIfExist(edge.node1)
	if not (id0 and id1) then
		return false
	end
	local p0, p1 = n0.pos, n1.pos
	local mid = { (p0[1]+p1[1])*0.5, (p0[2]+p1[2])*0.5 }
	local dx, dy = p0[1]-p1[1], p0[2]-p1[2]
	local radius = math.max(4, math.sqrt(dx*dx+dy*dy)*0.5 + 2)
	local ents = game.interface.getEntities({pos=mid, radius=radius}, {type="BASE_EDGE"})
	for _, eid in pairs(ents) do
		local comp = api.engine.getComponent(eid, api.type.ComponentType.BASE_EDGE)
		if comp and ((comp.node0==id0 and comp.node1==id1) or (comp.node0==id1 and comp.node1==id0)) then
			return true
		end
	end
	return false
end

function s.SimpleProposalSeq(data,options)
	osm_importer.options = assert(options, "Options not defined")
	s.data = data
	s.cbLevel = options.log_level or 1
	assert(type(s.cbLevel)=="number")

	local remaining = s.seqlist and s.nseq and s.seqi and s.seqi <= s.nseq
	if s.stop and remaining then
		print("Resume remaining edges:", (s.nseq - s.seqi + 1))
		s.stop = false
		s.pb = s.progressWindow()
		s.SimpleProposalSeqE()
		return
	end

	local restored = restoreRemaining(data)
	if restored then
		print("Resume stored remaining edges:", #restored)
		s.stop = false
		s.called = true
		s.finished = false
		s.seqlist = restored
		s.nseq = #restored
		s.seqi = 1
		s.count = 0
		s.nedges = { STREET = 0, TRACK = 0 }
		s.nosuc = { STREET = 0, TRACK = 0 }
		s.nskipped = { STREET = 0, TRACK = 0 }
		s.pb = s.progressWindow()
		s.SimpleProposalSeqE()
		return
	end

	s.stop = false
	s.called = true
	s.finished = false
	print("Start SimpleProposalCmdSeq")
	print(os.date())
	timer.start()
	print("Options: "..toString(options))

	local already_z
	for _, node in pairs(data.nodes) do
		already_z = node.pos and node.pos[3]
		break
	end
	if already_z then
		print("Node heights already set; skip.")
	else
		print("Set Nodes z height and tangents...")
		nodesheights.setAllNodesHeight(data.nodes, data.paths, data.edges)
	end

	local skipBuilt = s.hadRun == true
	s.seqlist = {}
	for key,edge in pairs(data.edges) do
		if (options.build_streets and edge.street)
		or (options.build_tracks and edge.track
			and (options.build_tramtracks or not edge.track.tram)
			and (options.build_subwaytracks or not edge.track.subway )) then
			edge.__key = key
			if skipBuilt and s.edgeAlreadyBuilt(edge) then
				-- already on the map from a previous Stage 3 run
			else
				table.insert(s.seqlist, edge)
			end
		end
	end
	s.hadRun = true
	s.nseq = #s.seqlist
	s.seqi = 1
	s.nedges = {
		STREET = 0,
		TRACK = 0,
	}
	s.nosuc = {
		STREET = 0,
		TRACK = 0,
	}
	s.nskipped = {
		STREET = 0,
		TRACK = 0,
	}
	s.count = 0
	print("Edges:  "..s.nseq)
	print(string.format("Estimated Time: %.0f min (%.2f h)", s.nseq/5/60, s.nseq/5/3600))
	s.pb = s.progressWindow()
	s.SimpleProposalSeqE()
end

function s.SimpleProposalSeqE()
	if s.seqi <= s.nseq and not s.stop then
		local edge = s.seqlist[s.seqi]
		s.seqi = s.seqi + 1
		s.count = s.count + 1
		s.pb:setProgress(s.count/math.max(1, s.nseq))
		s.pb:setTask(edge.track and "Track: "..edge.track.type or edge.street and "Street: "..edge.street.type)
		s.SimpleProposalSeqEdgeCmd(edge, s.cbLevel, true)
	else
		print("-------------------------------------------------------------")
		if s.stop then
			print("Process aborted !")
			print(string.format("Remaining Edges: %d", math.max(0, s.nseq - s.seqi + 1)))
			persistRemaining()
			s.finished = false
		else
			print("Finished SimpleProposalCmdSeq")
			s.seqlist = {}
			s.nseq = 0
			s.seqi = 1
			s.called = false
			s.finished = true
			_G.osm_importer_seq_keys = nil
		end
		print(os.date())
		local timedur = timer.stop()
		print(string.format("Time: %.2f min (%.2f h)", timedur/60, timedur/3600))
		print(string.format("Streets build failed: %d / %d  (%.1f %%)  skipped: %d",
			s.nosuc.STREET, s.nedges.STREET, failpct(s.nosuc.STREET, s.nedges.STREET), s.nskipped.STREET or 0))
		print(string.format("Tracks build failed: %d / %d  (%.1f %%)  skipped: %d",
			s.nosuc.TRACK, s.nedges.TRACK, failpct(s.nosuc.TRACK, s.nedges.TRACK), s.nskipped.TRACK or 0))
		if s.pb then
			s.pb:getParent():getParent():remove()
			s.pb = nil
		end
	end
end

function s.SimpleProposalSeqEdgeCmd(edge,cbLevel,retryWSmStreet)
	s.edge = edge
	local d2 = {
		nodes = {
			[edge.node0] = s.data.nodes[edge.node0],
			[edge.node1] = s.data.nodes[edge.node1],
		},
		edges = {
			edge
		},
	}
	s.replaceNode(d2,edge.node0)
	s.replaceNode(d2,edge.node1)
	if type(d2.nodes[edge.node0].id)=="number" and d2.nodes[edge.node0].id == d2.nodes[edge.node1].id then
		print("Node entity Id equal!", d2.nodes[edge.node1].id, toString(d2), toString(s.data.nodes[edge.node0]), toString(s.data.nodes[edge.node1]))
		error("")
	end

	if cbLevel>=1 then
		print("Cmd Edge #"..s.count.." - "..(edge.id or edge.__key or "").."  "..(cbLevel>=1 and string.format("N0: %s (%s) - N1: %s (%s) - %s", edge.node0, d2.nodes[edge.node0].id or "", edge.node1, d2.nodes[edge.node1].id or "", edge.track and "TRACK" or edge.street and "highway="..edge.street.type)) .. (cbLevel>=3 and toString(d2) or ""))
	end
	simpleproposal.SimpleProposalCmd(d2, nil, true, cbLevel, function(res, success)
		local etype = edge.track and "TRACK" or edge.street and "STREET"
		s.nedges[etype] = s.nedges[etype] + 1
		if res and res.skipped then
			s.nskipped[etype] = (s.nskipped[etype] or 0) + 1
		elseif not success then
			s.nosuc[etype] = s.nosuc[etype] + 1
		end
		s.SimpleProposalSeqE()
	end, retryWSmStreet)
end

function s.replaceNode(d,node)
	local id = s.getIdIfExist(node)
	if id then
		if s.cbLevel>=2 then
			print("Node already exist",id,toString(s.data.nodes[node]))
		end
		local basenode = api.engine.getComponent(id,api.type.ComponentType.BASE_NODE)
		d.nodes[node].id = id
		d.nodes[node].comp = basenode
	end
end

function s.getIdIfExist(node)
	local pos = assert(s.data.nodes[node].pos)
	local ents = game.interface.getEntities({pos=pos, radius=3}, {type="BASE_NODE"})  -- in most cases radius=0 is sufficient, but for sharp angles the node position is not in bounding box
	return tools.getNearestNode(pos,ents,1e-3)  -- choose  existing node only if very close
end

function s.progressWindow()
	local pb = api.gui.comp.ProgressBar.new()
	local window = api.gui.comp.Window.new("Progress (script will continue when closed)", pb)
	window:addHideOnCloseHandler()
	pb:setMinimumSize(api.gui.util.Size.new(500,10))
	return pb
end

return s
