#!/usr/bin/env python
#
# cmon
# 
# Copyright (C) 2011 by Yoshi Toshima <dolphin.duke@gmail.com>
#

"""Simple CUI performance monitor in terminal mode.

Using curses library, cpu usage and processes using cpu are listed
at given interval.
""" 

import os, sys, re, time, curses, logging, traceback, datetime
import threading

slock = threading.Lock()
LOG_FILENAME = 'perf.log'
logging.basicConfig(filename=LOG_FILENAME, level=logging.DEBUG)
logging.debug("logger initialized")

def capscr(scr, sy, sx):
  """Capture characters on screen from given position to right-bottom.
  """
  maxy = scr.getmaxyx()[0]
  lines = ""
  scr.move(sy, sx)
  ypos = sy
  while ypos < maxy:
    scr.move(ypos, 0)
    ln = scr.instr() 
    if not re.compile("^\s+$").match(ln):
      lines += scr.instr() + "\n" 
    ypos += 1
  return lines

def trim(string, lim):
  """Trim too long string to something like
     <beginning> ... <end>
     Currently, this function imposes hard-coded 80 characters
     low bound for lim.
  """
  if len(string) < lim: 
    return string
  if lim <= 80: 
    return string
  plen = (lim - 5)/2
  rs = string[:plen] + " ... " + string[-plen:]
  return rs

class ProcStatError(Exception):
  """Generic error class for ProcStat
  """
  def __init__(self, value):
    self.value = value
    Exception.__init__(self, value)

  def __str__(self):
    return repr(self.value)

class ProcStat:
  """Per process resource usage class.  Currently, process cpu
     usage in tikcs is handled.
  """
  UTICK_IDX = 0
  STICK_IDX = 1  
  def __init__(self, pid):
    self.pid = pid
    self.cmdline = "<unknown>"
    self.ticks = []
    self.prev_ticks = []
    self.tdiff = 0
    # Get command line.  This may fail depending on timing.
    # In case of error, set cmdline to <ioerror>.
    try:
      self.cmdline = trim(ProcStats.getCmdline(pid), 256)
    except IOError:
      self.cmdline = "<ioerror>"
       
  def __str__(self):
    return "%5s %5.2f " % (self.pid, self.getPct()) + self.cmdline

  def updateTicks(self):
    """Update tick data of pid after taking a copy.
    """
    self.prev_ticks = self.ticks
    self.ticks = ProcStats.getUtimeStime(self.pid)         

  def dataReady(self):
    """A Boolean test method to see whether this instance can return valid data.
       Most OSes provide tick counts for user, sys, etc.  To see the cpu usage
       percentage, we need at least two process cpu usage snapshots.  This method
       returns true if previous tick data is available.
    """
    return len(self.prev_ticks) > 0

  def getTickDiffByIdx(self, idx):
    """Returns tick diff for given idx.  idx is either 
       UTICK_IDX or  STICK_IDX.  
       Created to reduce length of line...
    """
    return (self.ticks[idx] - self.prev_ticks[idx])

  def userTickDiff(self):
    """Returns user tick diff
    """
    if not self.dataReady(): 
      raise ProcStatError("Data not available yet for pid " + self.pid)
    return self.getTickDiffByIdx(ProcStat.UTICK_IDX)

  def sysTickDiff(self):
    """Returns sys tick diff
    """
    if not self.dataReady(): 
      raise ProcStatError("Data not available yet for pid " + self.pid)
    return self.getTickDiffByIdx(ProcStat.STICK_IDX)

  def applyMeasurementTickDiff(self, tdiff):
    """Apply tick diff of last update.  updateTicks() shifts current
       ticks to prev_ticks and get current into ticks, but there was
       no simple way to update the time difference between prev_ticks
       and ticks.  So, the time difference should be updated independently
       by calling this method right after calling updateTicks().
    """
    self.tdiff = tdiff

  def getUserPct(self):
    """Returns user cpu usage of pid in float
    """
    try:
      return 100.0*float(self.userTickDiff())/self.tdiff
    except TypeError:
      print "E: getUserPct utick ", self.userTickDiff(), " tdiff ", self.tdiff
      raise

  def getSysPct(self):
    """Returns sys cpu usage of pid in float
    """
    return 100.0*float(self.sysTickDiff())/self.tdiff

  def getPct(self):
    """Returns user + sys cpu usage of pid in float
    """
    return self.getUserPct() + self.getSysPct()

class ProcStats:
  """A class which contains all process' ProcStat.  Individual process data
     can be looked up by pid.
  """
  NUMRE = re.compile("\d+")
  UTIME_IDX = 13
  STIME_IDX = 14
 
  def __init__(self):
    """Constructor
    """
    self.pss = []
    self.psmap = {}
    self.update_timestamp = 0
    self.prev_update_timestamp = 0

  def getMeasurementTickDiff(self):
    """returns time tick diff between previous update and current
       clock tick is assumed to be 10ms here
    """
    return (self.update_timestamp - self.prev_update_timestamp) * 100
  

  @staticmethod
  def getLivePids():
    """returns live proc ids based on /proc/\d+
    """
    el = os.listdir("/proc")
    procs = filter(lambda s: ProcStats.NUMRE.match(s) != None, el)
    return procs

  @staticmethod
  def getProcessStat(pid):
    """returns /proc/<pid>/stat line
       arg: pid in string
    """ 
    try:
      stfile = file("/proc/" + pid + "/stat")
      line = stfile.readline()
      stfile.close()
      return line
    except IOError:
      # return dummy entry
      return "0 "*44 
  
  @staticmethod
  def getComm(pid):
    """Get comm (short process name)
       arg: pid in string
    """
    return ProcStats.getProcessStat(pid).split(" ")[1]

  @staticmethod
  def getUtimeStime(pid):
    """Returns (utime, stime) for given process
    """
    data = ProcStats.getProcessStat(pid).split(" ")
    try:
      return (int(data[ProcStats.UTIME_IDX]), int(data[ProcStats.STIME_IDX]))
    except ValueError:
      print "E: getUtimeStime"
      print " data: " + data
      print " u: " + data[ProcStats.UTIME_IDX] + \
            " s: " + data[ProcStats.STIME_IDX]
      raise   
  
  @staticmethod
  def getCmdline(pid):
    """Get cmdline for given pid.
       arg: pid in string
    """
    clfile = file("/proc/" + pid + "/cmdline")
    ls = clfile.readlines()
    comm = ProcStats.getComm(pid) 
    rs = ""
    for l in ls:
      rs += " ".join(l.split("\0"))
    clfile.close()
    if rs == "": rs = comm
    return rs

  @staticmethod
  def getMissingElems(s1, s2):
    """generator method which finds s1 elements which are not in s2"""
    for elm in s1:
      if elm not in s2:
        yield elm

  def getProcStat(self, pid):
    """Get ProcStat for given pid.  Create one as needed.
    """
    if not self.psmap.has_key(pid):
      self.psmap[pid] = ProcStat(pid)
    return self.psmap[pid]

  def updateStat(self):
    """Update living process' ProcStat.
       ProcStat entries for exited processes are purged.
    """
    self.prev_update_timestamp = self.update_timestamp
    self.update_timestamp = time.time()
    pids = ProcStats.getLivePids()
    for pid in pids:
      ps = self.getProcStat(pid)
      ps.updateTicks()
      ps.applyMeasurementTickDiff(self.getMeasurementTickDiff())
    # purge non-existing process
    to_purge = filter(lambda e: e not in pids, self.psmap.keys()) 
    for tgt in to_purge:
      del self.psmap[tgt]

  def getTopCpuProcs(self, threshold=1.0):
    """Get ProcStat-s which have higher cpu usage than threshold, sorted in
       decending order.
    """
    pss = filter(lambda e: e.dataReady(), self.psmap.values())
    pss = filter(lambda e: e.getPct() > threshold, pss)
    pss.sort(cmp=lambda x, y: cmp(y.getPct(), x.getPct()))
    return pss

  def cloop(self):
    """Terminal mode(non-curses) main loop for debugging.
    """
    self.updateStat()
    time.sleep(0.2)
    while True:
      self.updateStat()
      if len(self.getTopCpuProcs()) > 0:
        print datetime.datetime.now()
        for elm in self.getTopCpuProcs():
          print elm
      time.sleep(1)

class CpuUse:
  """Class for processor resource usage
  """
  USER_IDX = 0
  NICE_IDX = 1
  SYS_IDX  = 2
  IDLE_IDX = 3
  IOWAIT_IDX  = 4
  IRQ_IDX     = 5
  SOFTIRQ_IDX = 6

  def __init__(self, name):
    self.name = name
    self.tick = 0
    self.prev_tick = 0
    self.vals = []
    self.prev_vals = []

  def name():
    """Returns name of this instance passed to constructor
    """
    return self.name

  def parseLineAndAdd(self, line):
    """ line: cpu tick number line
    """
    self.prev_vals = self.vals
    self.vals = map(lambda x: int(x), line.split())   
    self.prev_tick = self.tick
    self.tick = sum(self.vals)

  def pctReady(self): 
    """Boolean function which returns whether this instance can return valid
       data.  At least two snapshots are required to provide valid data.
       At second and later data update will copy previous data to prev_tick.
       Once prev_tick was populated, this function returns True. 
    """
    if self.prev_tick == 0:
      return False
    else:
      return True

  def valDiff(self, idx):
    """Returns vals (tick) diff for given idx.
       idx should be one of *_IDX in this class, e.g. USER_IDX, SYS_IDX
    """
    return self.vals[idx]-self.prev_vals[idx]

  def tickDiff(self):
    """Returns time difference in tick between the current and previous
       measurements.
    """
    return self.tick - self.prev_tick

  def userPct(self):
    """return user pct, None if data is not available
    """
    if not self.pctReady():
      return None
    return 100.0 * self.valDiff(CpuUse.USER_IDX)/self.tickDiff()

  def nicePct(self):
    """return nice pct, None if data is not available
    """
    if not self.pctReady():
      return None
    return 100.0 * self.valDiff(CpuUse.NICE_IDX)/self.tickDiff()

  def sysPct(self):
    """return nice pct, None if data is not available
    """
    if not self.pctReady():
      return None
    return 100.0 * self.valDiff(CpuUse.SYS_IDX)/self.tickDiff()

  def idlePct(self):
    """return nice pct, None if data is not available
    """
    if not self.pctReady():
      return None
    return 100.0 * self.valDiff(CpuUse.IDLE_IDX)/self.tickDiff()



class CpuMeter:
  """Class which holds some metrics, currently processor usage and process
     cpu usage.  This class also perform curses and terminal drawing.
  """
  DEFAULT_INTERVAL = 2.0
  CPU_ALL_PATTERN = re.compile("cpu\s+(?P<values>\d+\s+\d+\s+\d+\s+\d+.*)")
  CPU_N_PATTERN = re.compile("cpu(?P<cpu_num>\d+)\s+(?P<values>\d+\s+\d+\s+\d+\s+\d+.*)")
  def __init__(self, scr):
    self.scr = scr
    self.interval = CpuMeter.DEFAULT_INTERVAL
    self.cpu_uses = {}
    self.cpu_uses_key_list = []
    self.legend_width = 4
    if scr != None: self.initColors()
    self.command_queue = []
    self.popup_last_y = 1
    self.popup_last_x = 1
    self.menu = [
      {"label": "quit", "method": self.quit_command},
      {"label": "version", "method": self.version_command}
    ]
    self.process_stats = ProcStats()

  def quit_command(self):
    """quit command impl
    """
    self.alive = False 

  def version_command(self):
    """version command impl, not implemented properly yet.
    """
    self.showWindowSimpleText("version 0.1")

  def showWindowSimpleText(str):
    """show window with text, need more work
    """
    import textwrap
    self.popup_last_y += 1
    self.popup_last_x += 1
    (my, mx) = self.scr.getmaxyx()
    print_width = mx - self.popup_last_x - 2 - 4
    wrapped_strs = textwrap.wrap(str)
    tmaxw = max(map(lambda s: len(s), wrapped_strs))
    tmaxh = min(len(wrapped_strs), my - 2 - 4)
    win = scr.newwin(tmaxh, tmaxw, self.popup_last_y, self.popup_last_x)
    win.box()
    ln = 1
    for l in wrapped_strs:
      win.addstr(ln, 1, l)
    win.refresh()  
    popups.append(win)

  def getch(self):
    """simple shortcut to window.getch
    """
    return self.scr.getch()

  def queue_command(self, com):
    """queue command, string for now
    """
    self.command_queue.append(com)

  def initColors(self):
    """initialize curses colors
    """
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_GREEN)
    curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_RED)

  def loop(self, cui=False):
    """Repeats data gathering and output until quit is requested or
       interrupted by ctrl-c.
    """
    self.alive = True
    self.getProcStat() 
    
    if not cui:
      time.sleep(0.1)
      self.getProcStat() 
      self.cursesUpdate()

    while self.alive:
      time.sleep(self.interval)
      self.getProcStat() 
      if cui:
        self.nonCursesPrint()
      else:
        self.cursesUpdate()
    return self.last_lines

  def fixLegendWidth(self):
    """Determines cpu meter's legend with by the longest name of
       cpu_uses.
    """
    for k in self.cpu_uses.keys(): 
      cu = self.cpu_uses[k]
      self.legend_width = max(len(cu.name), self.legend_width)

  def barWidth(self):
    """Returns bar width considering legend width.
    """
    (my, mx) = self.scr.getmaxyx()
    return mx-self.legend_width

  def cursesUpdate(self):
    """Update screen using curses and data
    """
    if len(self.command_queue) > 0:
      comm = self.command_queue.pop(0)
      logging.debug("got command: " + comm)
      if comm == "quit":
        self.alive = False
        self.last_lines = capscr(self.scr, len(self.cpu_uses_key_list), 0)
        return
    # clear
    self.scr.erase()
    
    self.fixLegendWidth()
    bw = self.barWidth()
    ln = 0

    for k in self.cpu_uses_key_list:
      cu = self.cpu_uses[k]
      if not cu.pctReady(): break 

      self.scr.addstr(ln, 0, cu.name)
       
      cw = int((cu.userPct()/100.0)*bw)
      self.scr.addstr(ln, self.legend_width, " "*cw, curses.color_pair(1))
      
      self.scr.addstr(" "*int(bw*cu.nicePct()/100.0), curses.color_pair(2))
      self.scr.addstr(" "*int(bw*cu.sysPct()/100.0), curses.color_pair(3))
      self.scr.refresh()
      ln += 1
    self.cursesUpdateProcesses()

  def num_cpu_lines(self): 
    """returns the # of lines used by cpu bars
    """
    return len(self.cpu_uses_key_list)

  def cursesUpdateProcesses(self):
    """Process cpu usage is updated using curses lib.
    """
    proc_line_start = self.num_cpu_lines()
    n_process_lines = self.scr.getmaxyx()[0] - proc_line_start
  
    # draw process_stats
    pss = self.process_stats.getTopCpuProcs()
    py = proc_line_start
    px = 0
    for p in pss:
      try:
        self.scr.addstr(py, px, str(p))
        py = self.scr.getyx()[0]+1
        if py > self.scr.getmaxyx()[0]:
          break  
      except Exception:
        # addstr may end up with _curses.error if it tries to
        # add around the left-bottom of the screen
        break
    self.scr.refresh()

  def printCpuStat(self):
    """Print cpu usage by print, not using curses.
    """
    cu = self.getCpuUse("cpu")
    if cu.pctReady():
      print "cpu %3d %3d %3d %3d" % (cu.userPct(), cu.nicePct(), 
          cu.sysPct(), cu.idlePct())   
    for k in self.cpu_uses.keys():
      if k != "cpu":
        cu = self.cpu_uses[k]
        if cu.pctReady(): 
          print "%3s %3d %3d %3d %3d" \
             %  (k, cu.userPct(), cu.nicePct(), cu.sysPct(), cu.idlePct())   

  def nonCursesPrint(self):
    if len(self.process_stats.getTopCpuProcs()) > 0:
      print datetime.datetime.now()
      self.printCpuStat()
      self.printProcessStat()

  def printProcessStat(self):
    pss = self.process_stats.getTopCpuProcs()
    if len(pss) > 0:
      for ps in pss:
        print ps 

  def getCpuUse(self, key):
    """Returns CpuUse instance for key.  Instance is created as needed.
    """
    if not self.cpu_uses.has_key(key): 
      self.cpu_uses[key] = CpuUse(key)
      self.cpu_uses_key_list.append(key)
    return self.cpu_uses[key]

  def getProcStat(self):
    """Gather data from /proc/stat
    """
    ps = file("/proc/stat")
    for line in ps:
      if line.find("cpu") == 0: 
        mt = re.match(CpuMeter.CPU_ALL_PATTERN, line)
        if mt != None:
          self.getCpuUse("cpu").parseLineAndAdd(mt.group('values'))
          continue
        mt = re.match(CpuMeter.CPU_N_PATTERN, line) 
        if mt != None:
          self.getCpuUse(mt.group('cpu_num')).parseLineAndAdd(mt.group('values'))
          continue
    ps.close()
    self.getProcessStat()

  def getProcessStat(self):
    """get process data from /proc/<pid>/stat
    """
    self.process_stats.updateStat()

def doCUI():
  """non-curses mode main loop
  """
  meter = CpuMeter(None)
  meter.loop(cui=True)

def command_read_func(**args):
  """Thread entry point for key input reader
  """
  logging.debug("command_read_func started.")
  meter = args['cpu_meter']
  alive = True
  while alive:
    ch = meter.getch()
    if ch == ord('q'):   
      meter.queue_command("quit")
      logging.debug("logged quit command")
      alive = False

def main(scr):
  """main for curses mode
  """
  meter = CpuMeter(scr)
  t = threading.Thread(target=command_read_func, kwargs={"cpu_meter": meter})
  t.setDaemon(True)
  t.start()
  return meter.loop()

def platformSupported():
  """Returns true if platform is supported.
  """
  if sys.platform == "linux2": return True
  return False 

def showHelp():
  m = """usage: tplook [-ch] 
  options: 
    -c: character mode
    -h: show help and exit 
  command in curses:
    q: quit
  """
  print m

if  __name__ == '__main__' :
  import getopt
  optlist, args = getopt.getopt(sys.argv[1:], 'hvc', [])
  enableVerboseLogging = False
  useCUI = False

  for otup in optlist:
    opt = otup[0]
    if opt == '-h':
      showHelp()
      sys.exit(0)
    elif opt == '-v':
      enableVerboseLogging = True
    elif opt == '-c':
      useCUI = True

  if not platformSupported():
    print "Sorry, Your system type is not supported yet."
    sys.exit(0)

  try:
    if useCUI:
      doCUI()
    else:
      print curses.wrapper(main)
  except KeyboardInterrupt:
    logging.shutdown()
    sys.exit(0)
