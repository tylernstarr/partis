(ns ighutil.imgt
  (:require [clojure.java.io :as io]
            [clojure.string :as string]
            [clojure.edn :as edn]
            [flatland.useful.seq :refer [indexed]])
  (:import [net.sf.picard.reference FastaSequenceFile ReferenceSequence]))

(def GAP-CHARS #{\. \-})

(defn strip-allele [^String s]
  "Remove the allele from a string"
  (let [idx (.lastIndexOf s 42)]  ; 42 == '*'
    (if (< idx 0)
      s
      (.substring s 0 idx))))

(defn- nongap-lookup [sequence]
  (loop [result []
         sequence (indexed sequence)
         c 0]
    (if-let [[raw-idx base] (first sequence)]
      (if (GAP-CHARS base)
        (recur result (rest sequence) c)
        (recur (conj result [raw-idx c]) (rest sequence) (inc c)))
      (into {} result))))

(defn- parse-fasta [^FastaSequenceFile f]
  (lazy-seq
   (when-let [ref (.nextSequence f)]
     (cons ref (parse-fasta f)))))

(defn read-fasta [file]
  (with-open [ref-file (FastaSequenceFile. (io/file file) false)]
    (doall (parse-fasta ref-file))))

(def CYSTEINE-POSITION (* 3 (- 104 1)))

(defn create-cysteine-map []
  (let [f (-> "ighutil/ighv_aligned.fasta" io/resource io/file)
        extract-position (fn [^ReferenceSequence s]
                           (let [name (second (.. s (getName) (split "\\|")))
                                 pos-map (->> s
                                          (.getBases)
                                          (String.)
                                          nongap-lookup)]
                             [name (get pos-map CYSTEINE-POSITION)]))]
    (into {} (map extract-position (read-fasta f)))))

(defn slurp-edn-resource [resource-name]
  (with-open [reader (-> resource-name
                         io/resource
                         io/reader
                         (java.io.PushbackReader.))]
    (edn/read reader)))

(def cons-cysteine-map (slurp-edn-resource
                        "ighutil/ighv_cons_cysteine.clj"))

(def v-gene-meta (slurp-edn-resource "ighutil/ighv_cons.clj"))
