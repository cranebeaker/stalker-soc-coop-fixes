// Decompile AND disassemble every function whose qualified name contains one of the fragments (or whose entry address is given in hex).
// args: <output file> <fragment-or-0xADDR> [...]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;
import java.util.*;

public class DumpFuncs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        Set<Function> todo = new LinkedHashSet<>();
        for (int i = 1; i < a.length; i++) {
            if (a[i].startsWith("0x")) {
                Function f = getFunctionAt(toAddr(Long.parseLong(a[i].substring(2), 16)));
                if (f != null) todo.add(f);
            } else {
                for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
                    if (f.getName(true).contains(a[i])) todo.add(f);
                }
            }
        }
        for (Function f : todo) {
            out.println("// ===== " + f.getName(true) + " @ " + f.getEntryPoint() + " size " + f.getBody().getNumAddresses());
            DecompileResults r = d.decompileFunction(f, 120, monitor);
            out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// decompile failed");
            out.println("// ---- disassembly");
            for (Instruction ins : currentProgram.getListing().getInstructions(f.getBody(), true)) {
                out.println(ins.getAddress() + "  " + ins);
            }
        }
        out.close();
        println("dumped " + todo.size());
    }
}
