// For each range "start-end" (hex addresses), print every reference that jumps into the INTERIOR of the range (start < to <= end-1).
// args: <output file> <start-end> [<start-end> ...]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class CheckRefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        int bad = 0;
        for (int i = 1; i < a.length; i++) {
            String[] p = a[i].split("-");
            long s = Long.parseLong(p[0], 16), e = Long.parseLong(p[1], 16);
            for (long x = s + 1; x < e; x++) {
                Address ad = toAddr(x);
                for (Reference r : getReferencesTo(ad)) {
                    out.println("INTO-INTERIOR range " + a[i] + " addr " + ad + " from " + r.getFromAddress() + " type " + r.getReferenceType());
                    bad++;
                }
            }
            out.println("range " + a[i] + " checked");
        }
        out.println("interior references found: " + bad);
        out.close();
    }
}
