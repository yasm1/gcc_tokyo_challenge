import angr
import claripy
import json

from pathlib import Path


def forgive_symbol_segv(proj, symbol):
    sim_proc = None
    if proj.is_symbol_hooked(symbol):
        sim_proc = proj.hooked_by(proj.loader.find_symbol(symbol).rebased_addr)

    class ForgiveSegv(angr.SimProcedure):
        IS_FUNCTION = True
        local_vars = ('sim_proc_class', 'symbol_name')

        sim_proc_class = sim_proc.__class__
        symbol_name = symbol

        def run(self):
            args = []
            for i in range(7):
                try:
                    args.append(self.arg(i))
                except angr.SimProcedureArgumentError:
                    break

            self.project.unhook_symbol(self.symbol_name)
            # switch on STRICT_PAGE_ACCESS incase it is already off.
            # remove will cause error on removing unexisting switch.
            # self.state.options.update({angr.options.STRICT_PAGE_ACCESS})
            self.state.options.remove(angr.options.STRICT_PAGE_ACCESS)

            if self.sim_proc_class is None:
                self.call(self.state.solver.eval(self.state.regs.rip),
                          args, continue_at='enable_strict')
            else:
                ret = self.inline_call(self.sim_proc_class, *args).ret_expr
                self.state.options.update({angr.options.STRICT_PAGE_ACCESS})
                return ret

        def enable_strict(self):
            self.project.hook_symbol(self.symbol_name, ForgiveSegv())
            self.state.options.update({angr.options.STRICT_PAGE_ACCESS})

    proj.hook_symbol(symbol, ForgiveSegv())


FILE_NAME = '/tmp/input.bin'
BASE_ADDR = 0x400000
def crack(binpath):
    proj = angr.Project(binpath)

    argv = [binpath, FILE_NAME]
    state = proj.factory.full_init_state(args=argv,
                                         add_options={angr.options.STRICT_PAGE_ACCESS})

    # TODO: Maybe I shouldn't spcify concrete size.
    # Should size also be an data to solve dynamically?
    content = claripy.BVS('input', 200 * 8)
    input_file = angr.SimFile(FILE_NAME, content=content)
    state.fs.insert(FILE_NAME, input_file)

    # forgive segmentation faults in libc functions
    forgive_symbol_segv(proj, 'fopen')
    forgive_symbol_segv(proj, 'fprintf')
    forgive_symbol_segv(proj, 'malloc')
    forgive_symbol_segv(proj, 'fclose')
    # forgive_symbol_segv(proj, 'free') # will not finish
    # forgive_symbol_segv(proj, 'fseek') # will not finish

    simgr = proj.factory.simgr(state)
    # run to call to function crash
    simgr.run()

    if (len(simgr.errored) > 0):
        return (c \
                for e in simgr.errored \
                for c in e.state.solver.eval_upto(content, 1, cast_to=bytes))
    else:
        raise Exception("No crash detected")


if __name__ == '__main__':
    crash_inputs = crack('./simple_linter')
    p = Path("./angr_crashes")
    for i, ci in enumerate(crash_inputs):
        with (p / '{}.bin'.format(i)).open('wb') as f:
            f.write(ci)
