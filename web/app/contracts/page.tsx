"use client";
import { ContractEditor } from "@/components/ContractEditor";
import { ContractTable } from "@/components/ContractTable";
import { Shell } from "@/components/Shell";
import { Data, Empty } from "@/components/States";
import { listContracts } from "@/lib/api";
import { useApi } from "@/lib/useApi";

export default function ContractsPage() {
  const { state, reload } = useApi(listContracts);
  return (
    <Shell active="contracts">
      <span className="label">Contracts</span>
      <h1>
        What must <em>not</em> change
      </h1>
      <p className="lede">
        A behavioural contract is a versioned file that sits beside your prompt. It names the fields of the answer that
        must hold still, the changes to the input they must hold still under, and the tolerance the release gate
        enforces.
      </p>
      <div className="stack">
        <Data state={state} reload={reload} what="the contracts">
          {(contracts) =>
            contracts.length ? (
              <div className="card">
                <span className="label">Registered</span>
                <ContractTable contracts={contracts} />
              </div>
            ) : (
              <Empty title="No contracts registered yet">Register the example below to record a first trace.</Empty>
            )
          }
        </Data>
        <ContractEditor onRegistered={reload} />
      </div>
    </Shell>
  );
}
