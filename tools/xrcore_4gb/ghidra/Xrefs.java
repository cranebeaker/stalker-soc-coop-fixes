// Print every reference TO each given address (entry points).
// args: <output file> <hexaddr> [...]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class Xrefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        for (int i = 1; i < a.length; i++) {
            Address ad = toAddr(Long.parseLong(a[i], 16));
            out.println("== refs to " + ad);
            for (Reference r : getReferencesTo(ad)) {
                ghidra.program.model.listing.Function f = getFunctionContaining(r.getFromAddress());
                out.println("  from " + r.getFromAddress() + " " + r.getReferenceType() + " in " + (f == null ? "?" : f.getName(true)));
            }
        }
        out.close();
    }
}
